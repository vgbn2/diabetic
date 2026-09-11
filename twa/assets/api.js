/* Bio-Quant TWA — authenticated fetch wrapper.
   Attaches the Telegram auth header to every API call and redirects to the
   login gate on 401/403. */
async function apiFetch(path, opts) {
    opts = opts || {};
    var headers = Object.assign({}, opts.headers || {});
    var auth = BioAuth.authHeader();
    if (auth) headers["Authorization"] = auth;

    var res = await fetch(path, Object.assign({}, opts, { headers: headers }));
    if (res.status === 401 || res.status === 403) {
        location.href = "/login";
        throw new Error("unauthorized");
    }
    return res;
}

async function apiJson(path, opts) {
    var res = await apiFetch(path, opts);
    return res.json();
}
