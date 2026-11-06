#!/usr/bin/env python3
"""
臺北市街頭藝人全自動排程爬蟲 (GitHub Actions 專用)
每天自動抓取臺北市雙商圈（西門町 + 信義區）各日正取藝人名單與照片，並輸出為 data.js
"""

import urllib.request
import urllib.parse
import json
import os
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_API = "https://tpbusker.gov.taipei/tpbuskerfrontserver/api/Front"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json'
}

def http_get_json(endpoint):
    url = f"{REMOTE_API}{endpoint}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"[Warn] Fetch failed {endpoint}: {e}")
        return {'data': []}

def scrape_full_schedule(days_ahead=16):
    today = datetime.now()
    dates_to_scrape = [(today + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(-1, days_ahead)]
    print(f"Scraping dates from {dates_to_scrape[0]} to {dates_to_scrape[-1]} ({len(dates_to_scrape)} days)...")

    # 1. 取得點位與場次設定 (101:西門之星, 102:信義之星, 104:信義, 1:西門)
    place_rids = [101, 102, 104, 1]
    all_locations = []
    all_times = []
    times_seen = set()
    p_time_map = {}

    for p_id in place_rids:
        is_star = (p_id in (101, 102))
        district = '西門町' if p_id in (1, 101) else '信義區'
        p_locs = http_get_json(f"/VenueApplication/FetchLocationByPlaceRid?placeRid={p_id}").get('data', [])
        p_times = http_get_json(f"/VenueApplication/FetchPlaceTimeByPlaceRid?placeRid={p_id}").get('data', [])

        for t in p_times:
            p_time_map[t['placetimeRid']] = t
            if t['placetimeRid'] not in times_seen:
                times_seen.add(t['placetimeRid'])
                all_times.append(t)

        for l in p_locs:
            l['isStar'] = is_star
            l['placeRid'] = p_id
            l['district'] = district
        all_locations.extend(p_locs)

    # 2. 依月份拉取公告
    months_needed = set((int(d.split('-')[0]), int(d.split('-')[1])) for d in dates_to_scrape)
    all_bulletins = []

    def fetch_loc_month(item):
        loc, yr, mo = item
        p_id = loc['placeRid']
        v_id = loc['venueRid']
        res = http_get_json(f"/VenueApplication/FetchBulletinByParams?placeRid={p_id}&locationRid={v_id}&year={yr}&month={mo}")
        return loc, res.get('data', [])

    tasks = []
    for loc in all_locations:
        for yr, mo in months_needed:
            tasks.append((loc, yr, mo))

    print(f"Fetching bulletins for {len(tasks)} location-month pairs...")
    loc_bulletins = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        loc_bulletins = list(ex.map(fetch_loc_month, tasks))

    # 3. 逐日整理抽籤時段與藝人名單
    daily_results = {}

    for d_str in dates_to_scrape:
        day_slots = []
        for loc, items in loc_bulletins:
            matched = [it for it in items if it.get('bulletinDate', '').startswith(d_str)]
            slots = set((it['bulletinPlacetimerid'], it['bulletinLocationrid']) for it in matched)
            for time_rid, loc_rid in slots:
                day_slots.append((loc, time_rid, loc_rid))

        def fetch_buskers(slot):
            loc, time_rid, loc_rid = slot
            info_res = http_get_json(f"/VenueApplication/GetBulletinInfoList?locationRid={loc_rid}&placeTimeRid={time_rid}&date={d_str}")
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
                a['placeRid'] = loc['placeRid']
                a['district'] = loc['district']
                a['isStar'] = loc['isStar']
                if loc['isStar']:
                    a['starBadge'] = '⭐ 街藝之星'
                rank = a.get('bulletinRank')
                if rank is None or rank <= 1:
                    artists.append(a)
                else:
                    a['waitlistRank'] = f"備{rank - 1}"
                    waitlist.append(a)

            time_obj = p_time_map.get(time_rid, {})
            return {
                'placeRid': loc['placeRid'],
                'district': loc['district'],
                'isStar': loc['isStar'],
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

        with ThreadPoolExecutor(max_workers=10) as ex:
            schedule_details = list(ex.map(fetch_buskers, day_slots))

        total_artists = sum(len(s['artists']) for s in schedule_details)
        artists_with_photo = sum(sum(1 for a in s['artists'] if a.get('headShot')) for s in schedule_details)
        star_artists = sum(sum(1 for a in s['artists'] if a.get('isStar')) for s in schedule_details)
        ximen_artists = sum(sum(1 for a in s['artists'] if a.get('district') == '西門町') for s in schedule_details)
        xinyi_artists = sum(sum(1 for a in s['artists'] if a.get('district') == '信義區') for s in schedule_details)

        daily_results[d_str] = {
            'date': d_str,
            'stats': {
                'totalSlots': len(schedule_details),
                'totalArtists': total_artists,
                'artistsWithPhoto': artists_with_photo,
                'starArtists': star_artists,
                'ximenArtists': ximen_artists,
                'xinyiArtists': xinyi_artists
            },
            'schedule': schedule_details
        }
        print(f"[{d_str}] Done. Slots: {len(schedule_details)}, Artists: {total_artists} (Ximen: {ximen_artists}, Xinyi: {xinyi_artists}, Photo: {artists_with_photo})")

    full_payload = {
        'isSuccess': True,
        'updatedAt': datetime.now().isoformat(),
        'place': {
            'placeRid': 'ALL',
            'placeName': '臺北市雙商圈全覽（西門町 ＋ 信義區）',
            'totalLocations': len(all_locations),
            'isMerged': True
        },
        'locations': all_locations,
        'timeSlots': all_times,
        'daily': daily_results
    }

    # 輸出至 data.js
    out_path = os.path.join(BASE_DIR, 'data.js')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("window.INITIAL_BUSKER_FULL_DATA = " + json.dumps(full_payload, ensure_ascii=False, indent=2) + ";\n")
    print(f"Successfully generated {out_path} ({len(daily_results)} days cached)!")

if __name__ == '__main__':
    scrape_full_schedule(days_ahead=16)
