// ==UserScript==
// @name         臺北市街頭藝人每日照片偵測與檢視器
// @namespace    https://tpbusker.gov.taipei/
// @version      1.0.0
// @description  在西門徒步區等場地詳情頁一鍵開啟「每日街頭藝人照片偵測儀表板」，直接讀取官方 API 與高解析大頭照，無跨域限制！
// @author       Antigravity
// @match        https://tpbusker.gov.taipei/tpbusker/venue-detail*
// @match        https://tpbusker.gov.taipei/tpbusker/*
// @grant        none
// ==UserScript==

(function() {
    'use strict';

    // 建立浮動捷徑按鈕
    const fab = document.createElement('button');
    fab.id = 'tpbusker-detector-fab';
    fab.innerHTML = '<i class="fa fa-camera" style="margin-right:6px"></i> 偵測今日藝人照片';
    Object.assign(fab.style, {
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        zIndex: '999999',
        backgroundColor: '#2563eb',
        color: '#ffffff',
        border: 'none',
        borderRadius: '50px',
        padding: '12px 20px',
        fontSize: '14px',
        fontWeight: 'bold',
        boxShadow: '0 8px 24px rgba(37,99,235,0.4)',
        cursor: 'pointer',
        transition: 'all 0.2s ease',
        display: 'flex',
        alignItems: 'center'
    });

    fab.onmouseenter = () => { fab.style.transform = 'translateY(-2px) scale(1.03)'; fab.style.backgroundColor = '#1d4ed8'; };
    fab.onmouseleave = () => { fab.style.transform = 'none'; fab.style.backgroundColor = '#2563eb'; };

    // 點擊後開啟偵測彈窗
    fab.onclick = () => {
        openDetectorModal();
    };

    document.body.appendChild(fab);

    function openDetectorModal() {
        if (document.getElementById('tpbusker-detector-modal')) {
            document.getElementById('tpbusker-detector-modal').style.display = 'flex';
            return;
        }

        const modal = document.createElement('div');
        modal.id = 'tpbusker-detector-modal';
        Object.assign(modal.style, {
            position: 'fixed',
            inset: '0',
            backgroundColor: 'rgba(0,0,0,0.7)',
            backdropFilter: 'blur(6px)',
            zIndex: '1000000',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px'
        });

        const card = document.createElement('div');
        Object.assign(card.style, {
            width: '1000px',
            maxWidth: '95vw',
            height: '85vh',
            backgroundColor: '#ffffff',
            borderRadius: '16px',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)'
        });

        const header = document.createElement('div');
        header.innerHTML = `
            <div style="font-weight: bold; font-size: 16px; color: #1e293b;">
                📸 臺北市街頭藝人 - 每日照片偵測與名單
            </div>
            <button id="close-detector-modal" style="border:none;background:none;font-size:20px;cursor:pointer;color:#64748b;">✕</button>
        `;
        Object.assign(header.style, {
            padding: '14px 20px',
            borderBottom: '1px solid #e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            backgroundColor: '#f8fafc'
        });

        const content = document.createElement('div');
        content.id = 'detector-content-body';
        Object.assign(content.style, {
            flex: '1',
            overflowY: 'auto',
            padding: '20px'
        });
        content.innerHTML = '<div style="text-align:center;padding:40px;color:#64748b;">正在載入今日藝人照片與名單...</div>';

        card.appendChild(header);
        card.appendChild(content);
        modal.appendChild(card);
        document.body.appendChild(modal);

        document.getElementById('close-detector-modal').onclick = () => {
            modal.style.display = 'none';
        };

        // 載入資料
        loadTodayBuskerPhotos(content);
    }

    async function loadTodayBuskerPhotos(container) {
        const urlParams = new URLSearchParams(window.location.search);
        const currentPlaceRid = urlParams.get('placeRid') || '1';
        // 若在西門町 (1, 101) 或 信義區 (104, 102)，支援雙商圈全覽
        let targetPlaceRids = ['101', '102', '104', '1'];
        if (currentPlaceRid !== '1' && currentPlaceRid !== '101' && currentPlaceRid !== '104' && currentPlaceRid !== '102') {
            targetPlaceRids = [currentPlaceRid];
        }

        const now = new Date();
        const y = now.getFullYear();
        const m = now.getMonth() + 1;
        const d = String(now.getDate()).padStart(2, '0');
        const todayStr = `${y}-${String(m).padStart(2, '0')}-${d}`;

        const baseApi = 'https://tpbusker.gov.taipei/tpbuskerfrontserver/api/Front';
        const photoBase = 'https://tpbusker.gov.taipei/tpbusker/upfiles';

        try {
            let artists = [];

            for (const placeRid of targetPlaceRids) {
                const isStar = (placeRid === '101' || placeRid === '102');
                const district = (placeRid === '1' || placeRid === '101') ? '西門町' : '信義區';
                const locRes = await fetch(`${baseApi}/VenueApplication/FetchLocationByPlaceRid?placeRid=${placeRid}`).then(r => r.json());
                const locs = locRes.data || [];

                // 抓公告
                const bulletinTasks = locs.map(l =>
                    fetch(`${baseApi}/VenueApplication/FetchBulletinByParams?placeRid=${placeRid}&locationRid=${l.venueRid}&year=${y}&month=${m}`)
                        .then(r => r.json())
                        .then(res => ({ loc: l, items: (res.data || []).filter(it => it.bulletinDate && it.bulletinDate.startsWith(todayStr)) }))
                        .catch(() => ({ loc: l, items: [] }))
                );

                const allBulletins = await Promise.all(bulletinTasks);
                const slots = [];
                allBulletins.forEach(({ loc, items }) => {
                    const keys = new Set(items.map(i => `${i.bulletinPlacetimerid}_${i.bulletinLocationrid}`));
                    keys.forEach(k => {
                        const [tRid, lRid] = k.split('_');
                        slots.push({ loc, tRid, lRid });
                    });
                });

                // 抓藝人資料
                const artistTasks = slots.map(async ({ loc, tRid, lRid }) => {
                    try {
                        const info = await fetch(`${baseApi}/VenueApplication/GetBulletinInfoList?locationRid=${lRid}&placeTimeRid=${tRid}&date=${todayStr}`).then(r => r.json());
                        const raw = info.data || [];
                        const list = [];
                        raw.forEach(a => {
                            // Filter out waitlists (備取) - only Confirmed winners perform
                            const rank = a.bulletinRank;
                            if (rank && rank > 1) return;
                            if (a.isGroup && Array.isArray(a.isGroup) && a.isGroup.length > 0) {
                                a.isGroup.forEach(m => list.push({ ...a, ...m, isGroupMember: true }));
                            } else {
                                list.push(a);
                            }
                        });
                        return list.map(a => ({
                            ...a,
                            isStar,
                            district,
                            locName: `[${district}] ${isStar ? '⭐ ' : ''}${loc.venueName}`,
                            locSub: loc.venueSubname,
                            photoUrl: a.headShot ? `${photoBase}/${a.headShot}` : null
                        }));
                    } catch { return []; }
                });

                const artistsNested = await Promise.all(artistTasks);
                artists.push(...artistsNested.flat());
            }

            if (artists.length === 0) {
                container.innerHTML = `<div style="text-align:center;padding:50px;color:#64748b;">今日 (${todayStr}) 尚無演出排定或照片紀錄。</div>`;
                return;
            }

            container.innerHTML = `
                <div style="margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;">
                    <div style="font-size:13px;color:#475569;">
                        今日 (${todayStr}) 偵測到 <b>${artists.length}</b> 組藝人展演，共 <b>${artists.filter(a => a.photoUrl).length}</b> 張照片
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(220px, 1fr));gap:16px;">
                    ${artists.map(a => `
                        <div style="border:${a.isStar ? '2px solid #f59e0b' : '1px solid #e2e8f0'};border-radius:12px;overflow:hidden;background:#fff;box-shadow:${a.isStar ? '0 4px 12px rgba(245,158,11,0.2)' : '0 1px 3px rgba(0,0,0,0.05)'};">
                            <div style="position:relative;height:160px;background:#f1f5f9;display:flex;align-items:center;justify-content:center;overflow:hidden;">
                                ${a.photoUrl ? `<img src="${a.photoUrl}" style="width:100%;height:100%;object-fit:cover;">` : '<span style="color:#94a3b8;font-size:12px;">無照片</span>'}
                                ${a.isStar ? '<span style="position:absolute;top:8px;left:8px;background:linear-gradient(to right, #f59e0b, #fbbf24);color:#0f172a;font-size:10px;font-weight:bold;padding:2px 8px;border-radius:12px;box-shadow:0 2px 4px rgba(0,0,0,0.2);">⭐ 街藝之星</span>' : ''}
                            </div>
                            <div style="padding:12px;">
                                <div style="font-size:11px;color:${a.isStar ? '#d97706' : '#2563eb'};font-weight:700;">${a.locName}</div>
                                <div style="font-size:14px;font-weight:bold;color:#0f172a;margin-top:2px;">${a.buskerStageName || a.buskerName}</div>
                                <div style="font-size:11px;color:#64748b;margin-top:4px;">${a.performanceItem || ''}</div>
                                ${a.photoUrl ? `<a href="${a.photoUrl}" target="_blank" style="display:inline-block;margin-top:8px;font-size:11px;color:#2563eb;text-decoration:none;font-weight:600;">檢視大圖 ↗</a>` : ''}
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        } catch (err) {
            container.innerHTML = `<div style="color:red;padding:20px;">載入失敗: ${err.message}</div>`;
        }
    }
})();
