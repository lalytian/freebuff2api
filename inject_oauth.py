import sys

with open('/home/ubuntu/docker/freebuff2api/src/server.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 注入内存管理
oauth_backend = """
// ---------------------------------------------------------------------------
// OAuth CLI 授权会话（内存管理）
// ---------------------------------------------------------------------------
const oauthSessions = new Map();

function cleanOauthSessions() {
  const now = Date.now();
  for (const [id, s] of oauthSessions.entries()) {
    if (now - s.createdAt > 3600000) oauthSessions.delete(id);
  }
}
setInterval(cleanOauthSessions, 600000);
"""

target_proxy = "async function testProxyUrl(proxyUrl) {"
if target_proxy not in content:
    print("Error: target_proxy not found")
    sys.exit(1)
content = content.replace(target_proxy, oauth_backend + "\n" + target_proxy, 1)

# 2. 注入 API 路由
oauth_api = """
    if (apiPath === '/oauth/start' && req.method === 'POST') {
      const rand = randomBytes(6).toString('base64url').slice(0, 8);
      const fingerprintId = 'codebuff-cli-' + rand;
      const base = (buildEnv().CODEBUFF_API) || 'https://www.codebuff.com';
      try {
        const resp = await undiciFetch(base + '/api/auth/cli/code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'User-Agent': SDK_UA },
          body: JSON.stringify({ fingerprintId }),
        });
        const data = await resp.json();
        if (!resp.ok || !data || !data.loginUrl) {
          return sendJson(res, 500, { error: data?.message || data?.error || ('获取授权链接失败 HTTP ' + resp.status) });
        }
        const oauthId = randomBytes(16).toString('hex');
        oauthSessions.set(oauthId, {
          fingerprintId,
          fingerprintHash: data.fingerprintHash,
          expiresAt: data.expiresAt,
          loginUrl: data.loginUrl,
          status: 'pending',
          user: null,
          error: null,
          createdAt: Date.now(),
        });
        return sendJson(res, 200, { ok: true, oauthId, loginUrl: data.loginUrl });
      } catch (e) {
        return sendJson(res, 500, { error: String(e && e.message || e) });
      }
    }

    if (apiPath === '/oauth/status' && req.method === 'POST') {
      const { oauthId } = await readJson(req);
      const sess = oauthSessions.get(oauthId);
      if (!sess) return sendJson(res, 404, { error: '会话不存在或已过期' });
      if (sess.status === 'success') {
        return sendJson(res, 200, { ok: true, status: 'success', user: sess.user });
      }
      if (sess.status === 'error') {
        return sendJson(res, 200, { ok: false, status: 'error', error: sess.error });
      }

      const base = (buildEnv().CODEBUFF_API) || 'https://www.codebuff.com';
      const q = new URLSearchParams({
        fingerprintId: sess.fingerprintId,
        fingerprintHash: sess.fingerprintHash,
        expiresAt: String(sess.expiresAt),
      });
      try {
        const resp = await undiciFetch(base + '/api/auth/cli/status?' + q.toString(), {
          headers: { 'User-Agent': SDK_UA },
        });
        if (resp.status === 200) {
          const data = await resp.json();
          if (data && data.user && data.user.authToken) {
            sess.status = 'success';
            sess.user = {
              authToken: data.user.authToken,
              email: data.user.email || 'codebuff-user',
              id: data.user.id || '',
            };
            return sendJson(res, 200, { ok: true, status: 'success', user: sess.user });
          }
        } else if (resp.status === 401) {
          return sendJson(res, 200, { ok: true, status: 'pending' });
        } else {
          const errText = await resp.text();
          sess.status = 'error';
          sess.error = 'HTTP ' + resp.status + ': ' + errText.slice(0, 100);
          return sendJson(res, 200, { ok: false, status: 'error', error: sess.error });
        }
      } catch (e) {
        return sendJson(res, 200, { ok: true, status: 'pending', note: String(e && e.message || e) });
      }
      return sendJson(res, 200, { ok: true, status: 'pending' });
    }
"""

target_test_proxy = "if (apiPath === '/test_proxy' && req.method === 'POST') {"
if target_test_proxy not in content:
    print("Error: target_test_proxy not found")
    sys.exit(1)
content = content.replace(target_test_proxy, oauth_api + "\n    " + target_test_proxy, 1)

# 3. 注入前端按钮与弹窗逻辑
# 在 row 里增加 <button id="btnOAuth" style="background:#4285f4">🔑 Google OAuth 授权登录</button>
target_btn = '<button id="btnAdd">＋ 添加账号</button>'
replacement_btn = '<button id="btnOAuth" style="background:#4285f4">🔑 OAuth 登录加号</button><button id="btnAdd">＋ 手动添加</button>'
if target_btn not in content:
    print("Error: target_btn not found")
    sys.exit(1)
content = content.replace(target_btn, replacement_btn, 1)

# 在 wrap div 下方加入弹窗结构（或直接写进 js 处理）
oauth_frontend_js = """
  let oauthTimer = null;
  $('#btnOAuth').onclick = async () => {
    const box = $('#acctMsg');
    box.innerHTML = '<span class="ok">⏳ 正在向 Codebuff 请求 OAuth 授权链接...</span>';
    try {
      const j = await api('/oauth/start', { method: 'POST' });
      if (!j.ok || !j.loginUrl) throw new Error(j.error || '获取链接失败');
      
      box.innerHTML = '<div style="margin:10px 0;padding:12px;border:1px solid #4285f4;border-radius:8px;background:#131d33">'
        + '<div style="font-weight:bold;margin-bottom:6px">👉 请点击下方链接完成 Google 账号授权：</div>'
        + '<div style="margin-bottom:8px"><a href="' + esc(j.loginUrl) + '" target="_blank" style="color:#5b8cff;font-size:14px;word-break:break-all;text-decoration:underline">' + esc(j.loginUrl) + '</a></div>'
        + '<div id="oauthPollMsg" class="dim">🔄 等待浏览器授权中（自动轮询检测，最多 3 分钟）...</div>'
        + '</div>';

      window.open(j.loginUrl, '_blank');

      if (oauthTimer) clearInterval(oauthTimer);
      const start = Date.now();
      oauthTimer = setInterval(async () => {
        if (Date.now() - start > 180000) {
          clearInterval(oauthTimer);
          const p = $('#oauthPollMsg');
          if (p) p.innerHTML = '<span class="err">❌ 授权超时，请重试。</span>';
          return;
        }
        try {
          const res = await api('/oauth/status', { method: 'POST', body: JSON.stringify({ oauthId: j.oauthId }) });
          if (res.status === 'success' && res.user && res.user.authToken) {
            clearInterval(oauthTimer);
            const p = $('#oauthPollMsg');
            if (p) p.innerHTML = '<span class="ok">🎉 授权成功！账号：' + esc(res.user.email) + '，正在自动录入保存...</span>';
            
            // 自动追加进账号池并保存
            const current = collectAccts();
            current.push({
              name: res.user.email || ('codebuff-' + (current.length + 1)),
              token: res.user.authToken,
              socks5: '',
              enabled: true
            });
            const saveRes = await api('/accounts', { method: 'POST', body: JSON.stringify({ accounts: current }) });
            state.accounts = saveRes.accounts;
            render();
            $('#acctMsg').innerHTML = '<span class="ok">✅ 账号 ' + esc(res.user.email) + ' 已通过 OAuth 成功授权并入库！</span>';
          } else if (res.status === 'error') {
            clearInterval(oauthTimer);
            const p = $('#oauthPollMsg');
            if (p) p.innerHTML = '<span class="err">❌ 授权出错：' + esc(res.error) + '</span>';
          }
        } catch (err) {
          // ignore transient poll error
        }
      }, 2500);

    } catch (e) {
      box.innerHTML = '<span class="err">❌ ' + esc(e.message) + '</span>';
    }
  };
"""

target_bind = "$('#btnAdd').onclick="
if target_bind not in content:
    print("Error: target_bind not found")
    sys.exit(1)
content = content.replace(target_bind, oauth_frontend_js + "\n  " + target_bind, 1)

with open('/home/ubuntu/docker/freebuff2api/src/server.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("OAuth full integration complete!")
