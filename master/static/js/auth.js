/* Auth & API utilities */

const TOKEN_KEY = 'dist_unzip_token';

function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
}

function checkAuth() {
    if (!getToken()) {
        window.location.href = '/login';
        return false;
    }
    return true;
}

function logout() {
    clearToken();
    window.location.href = '/login';
}

async function apiGet(url) {
    const resp = await fetch(url, {
        headers: { 'Authorization': 'Bearer ' + getToken() }
    });
    if (resp.status === 401) {
        clearToken();
        window.location.href = '/login';
        throw new Error('未授权');
    }
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json();
}

async function apiPost(url, data) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + getToken()
        },
        body: JSON.stringify(data)
    });
    if (resp.status === 401) {
        clearToken();
        window.location.href = '/login';
        throw new Error('未授权');
    }
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json();
}

async function apiDelete(url) {
    const resp = await fetch(url, {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + getToken() }
    });
    if (resp.status === 401) {
        clearToken();
        window.location.href = '/login';
        throw new Error('未授权');
    }
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json();
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function renderNav(activePage) {
    const pages = [
        { href: '/submit', label: '提交' },
        { href: '/tasks', label: '任务' },
        { href: '/workers', label: '工作节点' },
        { href: '/users', label: '用户' },
        { href: '/dashboard', label: '仪表盘' }
    ];
    const nav = document.getElementById('main-nav');
    if (!nav) return;
    nav.innerHTML = pages.map(p =>
        `<a href="${p.href}" class="${p.href === activePage ? 'active' : ''}">${p.label}</a>`
    ).join('') + `<a href="#" onclick="logout();return false;" style="margin-left:auto;color:var(--danger)">退出登录</a>`;
}
