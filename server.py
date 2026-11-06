#!/usr/bin/env python3
"""
臺北市街頭藝人每日照片偵測與檢視系統 - 本地伺服器 & CORS 代理
"""

import http.server
import socket
import socketserver
import urllib.request
import urllib.error
import urllib.parse
import json
import os
import sys
import webbrowser
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_API = "https://tpbusker.gov.taipei/tpbuskerfrontserver/api/Front"
REMOTE_FILES = "https://tpbusker.gov.taipei/tpbusker/upfiles"

class BuskerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Accept, Authorization')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. 聚合每日街頭藝人快速 API
        if path == '/api/daily-buskers':
            self.handle_daily_buskers(query)
            return

        # 2. 通用 API 代理 (/api/proxy/...)
        if path.startswith('/api/proxy/'):
            subpath = path[len('/api/proxy/'):]
            target_url = f"{REMOTE_API}/{subpath}"
            if parsed.query:
                target_url += f"?{parsed.query}"
            self.proxy_request(target_url)
            return

        # 3. 圖片代理 (/api/image/...)
        if path.startswith('/api/image/'):
            filename = path[len('/api/image/'):]
            target_url = f"{REMOTE_FILES}/{filename}"
            self.proxy_request(target_url, is_image=True)
            return

        # 其他檔案依預設處理 (index.html, data.js 等)
        super().do_GET()

    def proxy_request(self, target_url, is_image=False):
        try:
            req = urllib.request.Request(
                target_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                self.send_response(resp.status)
                self.send_header('Content-Type', resp.headers.get('Content-Type', 'application/json'))
                self.send_header('Content-Length', str(len(data)))
                if is_image:
                    self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

    def handle_daily_buskers(self, query):
        raw_place = query.get('placeRid', ['ALL'])[0]
        date_str = query.get('date', [datetime.now().strftime('%Y-%m-%d')])[0]

        raw_upper = str(raw_place).upper()
        if raw_upper in ('ALL', '1,101,104,102', 'DUAL', ''):
            place_rids = [101, 102, 104, 1]  # 街藝之星優先置頂，包含西門與信義
            mode_name = '臺北市雙商圈全覽（西門町 ＋ 信義區）'
            is_merged_mode = True
        elif raw_upper in ('XIMEN', '1,101'):
            place_rids = [101, 1]
            mode_name = '西門町商圈 (含街藝之星)'
            is_merged_mode = False
        elif raw_upper in ('XINYI', '104,102', '104'):
            place_rids = [102, 104]
            mode_name = '信義商圈 (香堤大道/威秀/三越)'
            is_merged_mode = False
        elif raw_upper in ('STAR', 'STARS'):
            place_rids = [101, 102]
            mode_name = '⭐ 街藝之星特選專區 (西門 + 信義)'
            is_merged_mode = False
        else:
            try:
                place_rids = [int(raw_place)]
            except:
                place_rids = [101, 102, 104, 1]
            mode_name = f'指定場地 (placeRid={place_rids[0]})'
            is_merged_mode = False

        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            year = dt.year
            month = dt.month
        except:
            dt = datetime.now()
            date_str = dt.strftime('%Y-%m-%d')
            year = dt.year
            month = dt.month

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept': 'application/json'}

        def http_get_json(endpoint):
            url = f"{REMOTE_API}{endpoint}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode('utf-8'))

        try:
            all_schedule_details = []
            all_locations = []
            all_times = []
            times_seen = set()

            for p_id in place_rids:
                is_star = (p_id in (101, 102))
                district = '西門町' if p_id in (1, 101) else '信義區'
                p_locs = http_get_json(f"/VenueApplication/FetchLocationByPlaceRid?placeRid={p_id}").get('data', [])
                p_times = http_get_json(f"/VenueApplication/FetchPlaceTimeByPlaceRid?placeRid={p_id}").get('data', [])
                p_time_map = {t['placetimeRid']: t for t in p_times}

                for l in p_locs:
                    l['isStar'] = is_star
                    l['placeRid'] = p_id
                    l['district'] = district
                all_locations.extend(p_locs)

                for t in p_times:
                    if t['placetimeRid'] not in times_seen:
                        times_seen.add(t['placetimeRid'])
                        all_times.append(t)

                # 並行拉取當月公告
                def fetch_loc(loc):
                    v_id = loc['venueRid']
                    res = http_get_json(f"/VenueApplication/FetchBulletinByParams?placeRid={p_id}&locationRid={v_id}&year={year}&month={month}")
                    return loc, res.get('data', [])

                with ThreadPoolExecutor(max_workers=8) as ex:
                    loc_bulletins = list(ex.map(fetch_loc, p_locs))

                day_slots = []
                for loc, items in loc_bulletins:
                    matched = [it for it in items if it.get('bulletinDate', '').startswith(date_str)]
                    slots_in_loc = set((it['bulletinPlacetimerid'], it['bulletinLocationrid']) for it in matched)
                    for time_rid, loc_rid in slots_in_loc:
                        day_slots.append((loc, time_rid, loc_rid, is_star, p_id, district))

                def fetch_buskers(slot):
                    loc, time_rid, loc_rid, is_s, pr_id, dist = slot
                    info_res = http_get_json(f"/VenueApplication/GetBulletinInfoList?locationRid={loc_rid}&placeTimeRid={time_rid}&date={date_str}")
                    raw_artists = info_res.get('data', [])
                    all_extracted = []
                    for a in raw_artists:
                        if a.get('isGroup') and isinstance(a['isGroup'], list) and len(a['isGroup']) > 0:
                            for m in a['isGroup']:
                                m_obj = dict(a)
                                m_obj.update(m)
                                m_obj['isGroupMember'] = True
                                all_extracted.append(m_obj)
                        else:
                            all_extracted.append(a)
                    artists = []
                    waitlist = []
                    for a in all_extracted:
                        a['placeRid'] = pr_id
                        a['district'] = dist
                        a['isStar'] = is_s
                        if is_s:
                            a['starBadge'] = '⭐ 街藝之星'
                        rank = a.get('bulletinRank')
                        if rank is None or rank <= 1:
                            artists.append(a)
                        else:
                            a['waitlistRank'] = f"備{rank - 1}"
                            waitlist.append(a)
                    time_obj = p_time_map.get(time_rid, {})
                    return {
                        'placeRid': pr_id,
                        'district': dist,
                        'isStar': is_s,
                        'venueRid': loc['venueRid'],
                        'venueName': loc.get('venueName', ''),
                        'venueSubname': loc.get('venueSubname', ''),
                        'timeRid': time_rid,
                        'timeName': time_obj.get('placetimeName', f"時段{time_rid}"),
                        'timeStart': time_obj.get('placetimeStime', ''),
                        'timeEnd': time_obj.get('placetimeEtime', ''),
                        'artists': artists,
                        'waitlist': waitlist
                    }

                with ThreadPoolExecutor(max_workers=8) as ex:
                    schedule_details = list(ex.map(fetch_buskers, day_slots))
                all_schedule_details.extend(schedule_details)

            # 整理統計
            total_artists = sum(len(s['artists']) for s in all_schedule_details)
            artists_with_photo = sum(sum(1 for a in s['artists'] if a.get('headShot')) for s in all_schedule_details)
            star_artists = sum(sum(1 for a in s['artists'] if a.get('isStar')) for s in all_schedule_details)
            ximen_artists = sum(sum(1 for a in s['artists'] if a.get('district') == '西門町') for s in all_schedule_details)
            xinyi_artists = sum(sum(1 for a in s['artists'] if a.get('district') == '信義區') for s in all_schedule_details)

            place_info = {
                'placeRid': raw_place,
                'placeName': mode_name,
                'totalLocations': len(all_locations),
                'isMerged': is_merged_mode
            }

            response_payload = {
                'isSuccess': True,
                'date': date_str,
                'place': place_info,
                'stats': {
                    'totalSlots': len(all_schedule_details),
                    'totalArtists': total_artists,
                    'artistsWithPhoto': artists_with_photo,
                    'starArtists': star_artists,
                    'ximenArtists': ximen_artists,
                    'xinyiArtists': xinyi_artists
                },
                'locations': all_locations,
                'timeSlots': all_times,
                'schedule': all_schedule_details,
                'timestamp': datetime.now().isoformat()
            }

            # 自動快取至 data.js (保留全月份快取 window.INITIAL_BUSKER_FULL_DATA)
            try:
                data_js_path = os.path.join(BASE_DIR, 'data.js')
                full_prefix = ""
                if os.path.exists(data_js_path):
                    with open(data_js_path, 'r', encoding='utf-8') as rf:
                        existing_text = rf.read()
                    if "window.INITIAL_BUSKER_FULL_DATA = " in existing_text:
                        end_pos = existing_text.find(";\nwindow.INITIAL_BUSKER_DATA = ")
                        if end_pos != -1:
                            full_prefix = existing_text[:end_pos + 2]
                        else:
                            full_prefix = existing_text.rstrip() + "\n"
                with open(data_js_path, 'w', encoding='utf-8') as df:
                    if full_prefix:
                        df.write(full_prefix)
                    df.write("window.INITIAL_BUSKER_DATA = " + json.dumps(response_payload, ensure_ascii=False, indent=2) + ";\n")
            except Exception as e:
                pass

            resp_bytes = json.dumps(response_payload, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        except Exception as err:
            err_data = json.dumps({'isSuccess': False, 'message': str(err)}).encode('utf-8')
            self.send_response(500)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(err_data)))
            self.end_headers()
            self.wfile.write(err_data)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def main():
    import socket
    port = PORT
    for p in range(PORT, PORT + 20):
        try:
            server = socketserver.TCPServer(("", p), BuskerHandler)
            port = p
            break
        except OSError:
            continue

    local_ip = get_local_ip()

    print(f"\n" + "="*62)
    print(f"  [臺北市街頭藝人每日照片偵測與檢視系統] 伺服器已啟動！")
    print(f"  電腦瀏覽器: http://localhost:{port}/")
    print(f"  手機連線網址: http://{local_ip}:{port}/")
    print(f"  (手機與電腦連接同一個 Wi-Fi 即可直接掃碼或開啟！)")
    print(f"  目標場地: 雙核心雙商圈（西門町 ＋ 信義區，含街藝之星 ⭐）")
    print(f"  按 Ctrl+C 可停止伺服器")
    print("="*62 + "\n")

    try:
        webbrowser.open(f"http://localhost:{port}/")
    except:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n伺服器已關閉。")
        server.server_close()

if __name__ == '__main__':
    main()
