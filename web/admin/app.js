(function() {
    'use strict';

    var API_URL = window.location.origin;
    var token = localStorage.getItem('token');
    var refreshInterval;

    if (token) showDashboard();

    document.getElementById('login-btn').addEventListener('click', login);
    document.getElementById('logout-btn').addEventListener('click', logout);
    document.getElementById('password').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') login();
    });

    document.querySelectorAll('.tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            showTab(this.getAttribute('data-tab'));
        });
    });

    async function login() {
        var username = document.getElementById('username').value;
        var password = document.getElementById('password').value;
        var errorMsg = document.getElementById('error-msg');

        try {
            var res = await fetch(API_URL + '/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: username, password: password })
            });
            var data = await res.json();
            if (data.error) {
                errorMsg.textContent = data.message;
                errorMsg.classList.remove('hidden');
                return;
            }
            token = data.access_token;
            localStorage.setItem('token', token);
            showDashboard();
        } catch (e) {
            errorMsg.textContent = 'Connection failed';
            errorMsg.classList.remove('hidden');
        }
    }

    function logout() {
        fetch(API_URL + '/auth/logout', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token }
        });
        localStorage.removeItem('token');
        token = null;
        clearInterval(refreshInterval);
        document.getElementById('login-form').classList.remove('hidden');
        document.getElementById('dashboard').classList.add('hidden');
    }

    function showDashboard() {
        document.getElementById('login-form').classList.add('hidden');
        document.getElementById('dashboard').classList.remove('hidden');
        refreshData();
        refreshInterval = setInterval(refreshData, 5000);
    }

    async function refreshData() {
        try {
            var stats = await fetchAPI('/stats');
            var clients = await fetchAPI('/api/v1/clients');
            var tasks = await fetchAPI('/api/v1/tasks');
            var sessions = await fetchAPI('/api/v1/sessions');

            document.getElementById('status-dot').classList.add('connected');
            document.getElementById('status-text').textContent = 'Connected';

            if (stats) {
                setText('uptime', formatDuration(stats.uptime_seconds));
                setText('memory', (stats.memory && stats.memory.alloc_mb || 0) + ' MB');
                setText('goroutines', stats.runtime && stats.runtime.num_goroutine || 0);
                setText('clients-connected', stats.hub && stats.hub.clients && stats.hub.clients.connected || 0);
                setText('clients-workers', stats.hub && stats.hub.clients && stats.hub.clients.workers || 0);
                setText('clients-bots', stats.hub && stats.hub.clients && stats.hub.clients.bots || 0);
                setText('tasks-pending', stats.hub && stats.hub.tasks && stats.hub.tasks.pending || 0);
                setText('tasks-running', stats.hub && stats.hub.tasks && stats.hub.tasks.running || 0);
                setText('tasks-completed', stats.hub && stats.hub.tasks && stats.hub.tasks.completed || 0);
                setText('sessions-active', stats.hub && stats.hub.sessions || 0);
            }

            if (clients && clients.clients) renderClients(clients.clients);
            if (tasks && tasks.tasks) renderTasks(tasks.tasks);
            if (sessions && sessions.sessions) renderSessions(sessions.sessions);
        } catch (e) {
            document.getElementById('status-dot').classList.remove('connected');
            document.getElementById('status-text').textContent = 'Error';
        }
    }

    function setText(id, value) {
        document.getElementById(id).textContent = value;
    }

    async function fetchAPI(path) {
        var res = await fetch(API_URL + path, {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (res.status === 401) { logout(); return null; }
        return res.json();
    }

    function renderClients(clients) {
        var tbody = document.getElementById('clients-table');
        tbody.replaceChildren();
        clients.forEach(function(c) {
            var tr = document.createElement('tr');
            tr.appendChild(createCell((c.client_id || '').slice(0, 8) + '...'));
            tr.appendChild(createBadgeCell(c.type || '-', 'badge-success'));
            tr.appendChild(createBadgeCell(c.status || '-', c.status === 'connected' ? 'badge-success' : 'badge-error'));
            tr.appendChild(createCell(formatTime(c.connected_at)));
            tr.appendChild(createActionCell('Disconnect', function() { disconnectClient(c.client_id); }));
            tbody.appendChild(tr);
        });
    }

    function renderTasks(tasks) {
        var tbody = document.getElementById('tasks-table');
        tbody.replaceChildren();
        tasks.forEach(function(t) {
            var tr = document.createElement('tr');
            tr.appendChild(createCell((t.task_id || '').slice(0, 8) + '...'));
            tr.appendChild(createCell(t.task_type || '-'));
            tr.appendChild(createBadgeCell(t.status || '-', getStatusClass(t.status)));
            tr.appendChild(createCell(t.priority || '-'));
            tr.appendChild(createCell(formatTime(t.created_at)));
            tr.appendChild(createActionCell('Cancel', function() { cancelTask(t.task_id); }));
            tbody.appendChild(tr);
        });
    }

    function renderSessions(sessions) {
        var tbody = document.getElementById('sessions-table');
        tbody.replaceChildren();
        sessions.forEach(function(s) {
            var tr = document.createElement('tr');
            tr.appendChild(createCell((s.session_id || '').slice(0, 8) + '...'));
            tr.appendChild(createCell(s.username || '-'));
            tr.appendChild(createBadgeCell(s.role || '-', 'badge-success'));
            tr.appendChild(createCell(formatTime(s.created_at)));
            tr.appendChild(createCell(formatTime(s.expires_at)));
            tr.appendChild(createActionCell('Delete', function() { deleteSession(s.session_id); }));
            tbody.appendChild(tr);
        });
    }

    function createCell(text) {
        var td = document.createElement('td');
        td.textContent = text;
        return td;
    }

    function createBadgeCell(text, badgeClass) {
        var td = document.createElement('td');
        var span = document.createElement('span');
        span.className = 'badge ' + badgeClass;
        span.textContent = text;
        td.appendChild(span);
        return td;
    }

    function createActionCell(label, handler) {
        var td = document.createElement('td');
        var btn = document.createElement('button');
        btn.className = 'btn btn-danger';
        btn.textContent = label;
        btn.addEventListener('click', handler);
        td.appendChild(btn);
        return td;
    }

    function getStatusClass(status) {
        if (['completed', 'connected'].indexOf(status) >= 0) return 'badge-success';
        if (['pending', 'running', 'assigned'].indexOf(status) >= 0) return 'badge-warning';
        return 'badge-error';
    }

    function showTab(name) {
        document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
        document.querySelectorAll('.tab-content').forEach(function(t) { t.classList.remove('active'); });
        document.querySelector('[data-tab="' + name + '"]').classList.add('active');
        document.getElementById(name + '-tab').classList.add('active');
    }

    async function disconnectClient(id) {
        await fetch(API_URL + '/api/v1/clients/' + id + '/disconnect', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token }
        });
        refreshData();
    }

    async function cancelTask(id) {
        await fetch(API_URL + '/api/v1/tasks/' + id, {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + token }
        });
        refreshData();
    }

    async function deleteSession(id) {
        await fetch(API_URL + '/api/v1/sessions/' + id, {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + token }
        });
        refreshData();
    }

    function formatDuration(seconds) {
        if (!seconds) return '-';
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        var s = Math.floor(seconds % 60);
        return h + 'h ' + m + 'm ' + s + 's';
    }

    function formatTime(iso) {
        if (!iso) return '-';
        return new Date(iso).toLocaleString();
    }
})();
