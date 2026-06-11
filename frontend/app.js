// Wander — front-end for the AgentCore travel planner.
// Reads the API URL + Cognito config from /config.json (injected at deploy time
// by the CDK FrontendStack). The Function URL is IAM-authenticated, so we fetch
// short-lived, unauthenticated AWS credentials from the Cognito Identity Pool
// and SigV4-sign the request with them (via aws4fetch) before rendering the
// markdown response.

import { AwsClient } from "https://esm.sh/aws4fetch@1.0.20";

const els = {
  prompt: document.getElementById("prompt"),
  go: document.getElementById("go"),
  status: document.getElementById("status"),
  result: document.getElementById("result"),
  error: document.getElementById("error"),
  examples: document.getElementById("examples"),
};

let CFG = { apiUrl: null, identityPoolId: null, region: null };

// Load deploy-time config (the CDK BucketDeployment writes this alongside the app)
async function loadConfig() {
  try {
    const res = await fetch("config.json", { cache: "no-store" });
    if (res.ok) {
      const cfg = await res.json();
      CFG = {
        apiUrl: cfg.apiUrl || null,
        identityPoolId: cfg.identityPoolId || null,
        region: cfg.region || null,
      };
    }
  } catch (_) { /* fall through to error on submit */ }
}

// --- Cognito unauthenticated credentials -----------------------------------
// Call the Cognito Identity JSON API directly (these calls need no signing for
// an unauthenticated identity pool). Cache the result until it nears expiry.
let _creds = null; // { accessKeyId, secretAccessKey, sessionToken, expiresAt }

async function cognitoCall(target, body) {
  const res = await fetch(`https://cognito-identity.${CFG.region}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityService.${target}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Cognito ${target} failed (${res.status})`);
  }
  return res.json();
}

async function getCredentials() {
  // Reuse cached creds while they have >2 min of life left.
  if (_creds && _creds.expiresAt - Date.now() > 120_000) return _creds;

  const { IdentityId } = await cognitoCall("GetId", {
    IdentityPoolId: CFG.identityPoolId,
  });
  const { Credentials } = await cognitoCall("GetCredentialsForIdentity", {
    IdentityId,
  });

  _creds = {
    accessKeyId: Credentials.AccessKeyId,
    secretAccessKey: Credentials.SecretKey,
    sessionToken: Credentials.SessionToken,
    // Expiration is epoch seconds.
    expiresAt: Credentials.Expiration * 1000,
  };
  return _creds;
}

function setLoading(on) {
  els.go.disabled = on;
  els.status.innerHTML = on
    ? '<span class="spinner"></span> Planning your trip… (this can take up to a minute)'
    : "";
}

function show(el, html) {
  el.innerHTML = html;
  el.classList.remove("hidden");
}
function hide(el) { el.classList.add("hidden"); }

async function plan() {
  const prompt = els.prompt.value.trim();
  hide(els.error);
  hide(els.result);
  if (!prompt) {
    show(els.error, "Please enter where you'd like to go.");
    return;
  }
  if (!CFG.apiUrl || !CFG.identityPoolId || !CFG.region) {
    show(els.error, "App is not configured (missing API URL or auth). Re-deploy the frontend.");
    return;
  }

  setLoading(true);
  try {
    const creds = await getCredentials();
    const aws = new AwsClient({
      accessKeyId: creds.accessKeyId,
      secretAccessKey: creds.secretAccessKey,
      sessionToken: creds.sessionToken,
      service: "lambda",
      region: CFG.region,
    });

    const res = await aws.fetch(CFG.apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(data.error || `Request failed (${res.status})`);
    }
    // Some models emit <thinking>…</thinking> reasoning into the text; hide it.
    const md = (data.result || data.raw || "_No itinerary returned._")
      .replace(/<thinking>[\s\S]*?<\/thinking>/gi, "")
      .trim();
    const meta = data.session_id
      ? `<div class="meta">session: ${data.session_id}</div>`
      : "";
    show(els.result, marked.parse(md) + meta);
    els.result.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    show(els.error, `Sorry — something went wrong.<br><small>${err.message}</small>`);
  } finally {
    setLoading(false);
  }
}

// Wire up interactions
els.go.addEventListener("click", plan);
els.prompt.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") plan();
});
els.examples.addEventListener("click", (e) => {
  if (e.target.classList.contains("chip")) {
    els.prompt.value = e.target.textContent;
    els.prompt.focus();
  }
});

loadConfig();
