window.Telegram = window.Telegram || {};
window.Telegram.WebApp = (function () {
    var WebApp = {};
    var parentWindow = window.parent;

    function parseQuery(query) {
        var result = {};
        if (!query) {
            return result;
        }
        String(query).split("&").forEach(function (part) {
            if (!part) {
                return;
            }
            var pair = part.split("=");
            var key = decodeURIComponent(pair.shift().replace(/\+/g, " "));
            var value = decodeURIComponent(pair.join("=").replace(/\+/g, " "));
            result[key] = value;
        });
        return result;
    }

    function parseHashParams(hash) {
        hash = (hash || "").replace(/^#/, "");
        if (!hash) {
            return {};
        }
        if (hash.indexOf("=") === -1) {
            return { _path: hash };
        }
        return parseQuery(hash);
    }

    function postEvent(eventType, eventData) {
        var payload = JSON.stringify({
            eventType: eventType,
            eventData: eventData || {}
        });

        if (window.TelegramWebviewProxy && typeof window.TelegramWebviewProxy.postEvent === "function") {
            window.TelegramWebviewProxy.postEvent(eventType, JSON.stringify(eventData || {}));
            return;
        }
        if (window.external && typeof window.external.notify === "function") {
            window.external.notify(payload);
            return;
        }
        if (parentWindow && parentWindow !== window) {
            parentWindow.postMessage(payload, "*");
        }
    }

    function byteLength(str) {
        return new TextEncoder().encode(str).length;
    }

    var hashParams = parseHashParams(window.location.hash);
    var initData = hashParams.tgWebAppData || "";
    var initUnsafe = parseQuery(initData);
    if (initUnsafe.user) {
        try {
            initUnsafe.user = JSON.parse(initUnsafe.user);
        } catch (e) {}
    }

    WebApp.initData = initData;
    WebApp.initDataUnsafe = initUnsafe;
    WebApp.version = hashParams.tgWebAppVersion || "8.0";
    WebApp.platform = hashParams.tgWebAppPlatform || "unknown";
    WebApp.isExpanded = false;
    WebApp.viewportHeight = window.innerHeight;

    WebApp.ready = function () {
        postEvent("web_app_ready");
    };
    WebApp.expand = function () {
        postEvent("web_app_expand");
        WebApp.isExpanded = true;
    };
    WebApp.close = function () {
        postEvent("web_app_close");
    };
    WebApp.sendData = function (data) {
        if (!data || !String(data).length) {
            return;
        }
        if (byteLength(String(data)) > 4096) {
            console.error("WebApp.sendData: данные длиннее 4096 байт");
            return;
        }
        postEvent("web_app_data_send", { data: String(data) });
    };
    WebApp.openLink = function (url, options) {
        postEvent("web_app_open_link", { url: url, options: options || {} });
    };
    WebApp.switchInlineQuery = function (query, choose_chat_types) {
        postEvent("web_app_switch_inline_query", {
            query: query,
            choose_chat_types: choose_chat_types
        });
    };

    return WebApp;
})();
window.TelegramWebApp = window.Telegram.WebApp;
