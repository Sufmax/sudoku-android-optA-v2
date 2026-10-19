/** Page de connexion rendue par le Worker (aucun asset du dashboard n'est servi sans session). */
export function loginPage(error = ""): Response {
  const html = `<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sudoku Bot — Connexion</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;600;800;900&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0}body{min-height:100vh;background:#F5F1E8;color:#0B0B0C;font-family:"Inter Tight",system-ui,sans-serif;display:grid;place-items:center;padding:24px}
main{width:min(560px,100%)}small{font-size:11px;letter-spacing:.18em;text-transform:uppercase;font-weight:600}
h1{font-size:clamp(56px,14vw,112px);line-height:.86;font-weight:900;letter-spacing:-.04em;margin:18px 0 36px}
h1 span{background:#C6FF1A;padding:0 .08em}
label{display:block;margin-bottom:10px}input{width:100%;font:600 20px "Inter Tight",sans-serif;padding:18px 22px;border:3px solid #0B0B0C;border-radius:999px;background:transparent;outline:none}
input:focus{box-shadow:5px 5px 0 #6B2BFF}
button{margin-top:22px;display:inline-flex;gap:18px;align-items:center;font:800 18px "Inter Tight",sans-serif;color:#fff;background:#0B0B0C;border:3px solid #0B0B0C;border-radius:999px;padding:16px 26px;cursor:pointer;box-shadow:6px 6px 0 #6B2BFF;transition:transform .08s,box-shadow .08s}
button:active{transform:translate(4px,4px);box-shadow:2px 2px 0 #6B2BFF}.err{margin-top:18px;color:#0B0B0C;background:#FF3B1F22;border-left:4px solid #FF3B1F;padding:10px 14px;font-weight:600}
</style></head><body><main>
<small>Sudoku Bot · Accès privé</small>
<h1>Entrer<br>dans la <span>grille.</span></h1>
<form method="post" action="/api/login">
<label><small>Mot de passe</small></label>
<input type="password" name="password" autocomplete="current-password" required autofocus>
<button type="submit">Connexion <span aria-hidden="true">→</span></button>
${error ? `<p class="err">${error}</p>` : ""}
</form></main></body></html>`;
  return new Response(html, { status: error ? 401 : 200, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Frame-Options": "DENY" } });
}
