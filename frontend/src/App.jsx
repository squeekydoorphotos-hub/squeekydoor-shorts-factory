import { useState, useEffect, useCallback } from "react"

const API = import.meta.env.VITE_API_URL || "http://localhost:8000"

const C = {
  dark:    "#000000",
  card:    "#0D0D0D",
  field:   "#141414",
  emerald: "#4a8c5c",
  gold:    "#C9A443",
  dim:     "#888888",
  text:    "#CCCCCC",
  red:     "#CC4444",
  orange:  "#CC7700",
  border:  "#1E1E1E",
}

const css = {
  page:  { minHeight:"100vh", background:C.dark, color:C.text,
           fontFamily:"'Georgia', 'Palatino Linotype', serif" },
  card:  { background:C.card, borderRadius:4, padding:24,
           border:`1px solid ${C.border}` },
  input: { width:"100%", background:C.field, border:`1px solid ${C.border}`,
           borderRadius:8, padding:"10px 14px", color:C.text, fontSize:14,
           outline:"none", boxSizing:"border-box" },
  btn:   (bg=C.emerald, fg=C.dark) => ({
           background:bg, color:fg, border:"none", borderRadius:2,
           padding:"10px 20px", fontWeight:600, fontSize:13, cursor:"pointer",
           letterSpacing:1, textTransform:"uppercase",
           fontFamily:"'Segoe UI', Arial, sans-serif" }),
  label: { fontSize:12, color:C.dim, marginBottom:4, display:"block" },
  sec:   { fontSize:10, fontWeight:700, color:C.emerald, letterSpacing:3,
           textTransform:"uppercase", marginBottom:8, fontFamily:"'Segoe UI', Arial, sans-serif" },
}

const TOKENS_PER_CLIP = 0.5

// ── API ────────────────────────────────────────────────────────────
function apiFetch(path, opts={}, token=null) {
  const headers = { "Content-Type":"application/json", ...(opts.headers||{}) }
  if (token) headers["Authorization"] = `Bearer ${token}`
  return fetch(API + path, { ...opts, headers })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.detail || "Error") }))
}

// ── VIRALITY SCORE badge ───────────────────────────────────────────
function ViralityBadge({ score, tag }) {
  if (!score && score !== 0) return null
  const colour = score >= 85 ? C.emerald : score >= 70 ? C.gold :
                 score >= 55 ? C.orange  : C.dim
  const fire   = score >= 85 ? "🔥" : score >= 70 ? "⚡" :
                 score >= 55 ? "✨" : "💤"
  return (
    <div style={{ display:"inline-flex", alignItems:"center", gap:6,
                  background:`${colour}18`, border:`1px solid ${colour}50`,
                  borderRadius:20, padding:"3px 10px" }}>
      <span style={{ fontSize:14 }}>{fire}</span>
      <span style={{ color:colour, fontWeight:900, fontSize:15 }}>{score}</span>
      <span style={{ color:colour, fontSize:11, fontWeight:600 }}>{tag}</span>
    </div>
  )
}

// ── TOKEN ESTIMATOR ────────────────────────────────────────────────
function TokenEstimator({ clipCount, userTokens, plan, nextFreeJobAt }) {
  const cost    = Math.round(clipCount * TOKENS_PER_CLIP * 10) / 10
  const after   = Math.round((userTokens - cost) * 10) / 10
  const canDo   = userTokens >= cost
  const weeks   = after > 0 ? Math.floor(after / (10 * TOKENS_PER_CLIP)) : 0

  // Free tier weekly reset
  let freeMsg = null
  if (plan === "free" && nextFreeJobAt) {
    const diff = new Date(nextFreeJobAt) - new Date()
    if (diff > 0) {
      const days  = Math.floor(diff / 86400000)
      const hours = Math.floor((diff % 86400000) / 3600000)
      freeMsg = `Free plan resets in ${days}d ${hours}h`
    }
  }

  return (
    <div style={{ background:C.field, borderRadius:10,
                  padding:"14px 16px", border:`1px solid ${C.border}` }}>
      <div style={{ display:"flex", justifyContent:"space-between",
                    alignItems:"center", marginBottom:10 }}>
        <span style={css.sec}>Token Estimate</span>
        <span style={{ fontSize:11, color:C.dim }}>1 clip = 0.5 tokens</span>
      </div>

      {/* Cost bar */}
      <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:8 }}>
        <div style={{ flex:1, height:6, background:C.border, borderRadius:3 }}>
          <div style={{ width:`${Math.min(100, (cost/Math.max(userTokens,1))*100)}%`,
                        height:"100%", borderRadius:3,
                        background:canDo ? C.emerald : C.red,
                        transition:"width .3s" }}/>
        </div>
        <span style={{ color: canDo ? C.emerald : C.red,
                       fontWeight:700, fontSize:16, minWidth:60, textAlign:"right" }}>
          −{cost} tokens
        </span>
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:8 }}>
        <div style={{ textAlign:"center" }}>
          <div style={{ color:C.gold, fontWeight:900, fontSize:20 }}>{clipCount}</div>
          <div style={{ color:C.dim, fontSize:11 }}>clips</div>
        </div>
        <div style={{ textAlign:"center" }}>
          <div style={{ color: canDo ? C.text : C.red,
                        fontWeight:900, fontSize:20 }}>{after}</div>
          <div style={{ color:C.dim, fontSize:11 }}>tokens left</div>
        </div>
        <div style={{ textAlign:"center" }}>
          <div style={{ color:C.emerald, fontWeight:900, fontSize:20 }}>{weeks}wk</div>
          <div style={{ color:C.dim, fontSize:11 }}>of 10 clips/wk</div>
        </div>
      </div>

      {freeMsg && (
        <div style={{ marginTop:10, background:"#FF8C0020", border:`1px solid ${C.orange}40`,
                      borderRadius:8, padding:"8px 12px", color:C.orange, fontSize:12 }}>
          ⏳ {freeMsg}
        </div>
      )}
      {!canDo && (
        <div style={{ marginTop:10, background:"#FF555520", border:`1px solid ${C.red}40`,
                      borderRadius:8, padding:"8px 12px", color:C.red, fontSize:12 }}>
          Not enough tokens — buy a top-up or upgrade your plan
        </div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════
//  TOP-LEVEL APP
// ══════════════════════════════════════════════════════════════════

export default function App() {
  const [token,       setToken]       = useState(() => localStorage.getItem("sdp_token") || "")
  const [user,        setUser]        = useState(null)
  const [page,        setPage]        = useState("landing")
  const [selectedJob, setSelectedJob] = useState(null)

  const login = (tok, userData) => {
    localStorage.setItem("sdp_token", tok)
    setToken(tok); setUser(userData); setPage("dashboard")
  }
  const logout = () => {
    localStorage.removeItem("sdp_token")
    setToken(""); setUser(null); setPage("landing")
  }

  useEffect(() => {
    if (token && !user) {
      apiFetch("/auth/me", {}, token)
        .then(u => { setUser(u); setPage("dashboard") })
        .catch(() => { localStorage.removeItem("sdp_token"); setToken("") })
    }
  }, [])

  useEffect(() => {
    const p = new URLSearchParams(window.location.search)
    if ((p.get("sub") === "success" || p.get("topup") === "success") && token) {
      apiFetch("/auth/me", {}, token).then(u => setUser(u))
      setPage("dashboard")
      window.history.replaceState({}, "", window.location.pathname)
    }
    // Handle email verification link
    if (p.get("verify")) {
      setPage("verify")
    }
    // Handle password reset link
    if (p.get("reset")) {
      setPage("reset")
    }
  }, [token])

  return (
    <div style={css.page}>
      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
      <Header user={user} onLogout={logout} onNav={setPage} />
      {page==="landing"   && <Landing   onNav={setPage} />}
      {page==="pricing"   && <Pricing   token={token} onNav={setPage} />}
      {page==="login"     && <Login     onLogin={login} onNav={setPage} />}
      {page==="register"  && <Register  onLogin={login} onNav={setPage} />}
      {page==="dashboard" && user && <Dashboard user={user} setUser={setUser} token={token} onNav={setPage} onViewClips={(jobId) => { setSelectedJob(jobId); setPage("clips") }} />}
      {page==="new"       && user && <NewJob    user={user} setUser={setUser} token={token} onNav={setPage} />}
      {page==="verify"    && <VerifyEmail onNav={setPage} />}
      {page==="clips"     && <ClipPicker jobId={selectedJob} token={token} onNav={setPage} />}
      {page==="forgot"    && <ForgotPassword onNav={setPage} />}
      {page==="reset"     && <ResetPassword onNav={setPage} />}
      {page==="check-email" && <CheckEmail onNav={setPage} />}
    </div>
  )
}

// ── HEADER ────────────────────────────────────────────────────────

function Header({ user, onLogout, onNav }) {
  return (
    <header style={{ background:C.card, borderBottom:`1px solid ${C.border}`,
                     padding:"0 24px", display:"flex", alignItems:"center",
                     height:64, gap:16 }}>
      <span style={{ cursor:"pointer", display:"flex", alignItems:"center", gap:10 }}
            onClick={() => onNav("landing")}>
        <span style={{ color:C.gold, fontWeight:700, fontSize:22,
                       fontFamily:"'Georgia', serif", letterSpacing:1 }}>SDP</span>
        <span style={{ color:C.text, fontWeight:400, fontSize:16,
                       fontFamily:"'Georgia', serif", letterSpacing:3,
                       textTransform:"uppercase" }}>Shorts</span>
      </span>
      <span style={{ flex:1 }}/>
      {user ? (
        <>
          {user.is_admin && (
            <div style={{ background:"#C9A44322", borderRadius:2, padding:"4px 14px",
                          fontSize:11, color:C.gold, fontWeight:700, letterSpacing:2,
                          textTransform:"uppercase", border:`1px solid ${C.gold}`,
                          fontFamily:"Arial, sans-serif" }}>
              ★ ADMIN · NO LIMITS
            </div>
          )}
          <div style={{ background:C.field, borderRadius:20, padding:"4px 14px",
                        fontSize:13, color:C.gold, fontWeight:700, display:"flex",
                        alignItems:"center", gap:6 }}>
            ⚡ {user.is_admin ? "∞" : user.tokens} tokens
          </div>
          <button style={css.btn(C.emerald)} onClick={() => onNav("new")}>+ New Job</button>
          <button style={css.btn(C.field, C.dim)} onClick={() => onNav("dashboard")}>Dashboard</button>
          <button style={css.btn(C.field, C.dim)} onClick={onLogout}>Logout</button>
        </>
      ) : (
        <>
          <button style={css.btn(C.field, C.text)} onClick={() => onNav("pricing")}>Pricing</button>
          <button style={css.btn(C.field, C.text)} onClick={() => onNav("login")}>Login</button>
          <button style={css.btn(C.emerald)} onClick={() => onNav("register")}>Start Free</button>
        </>
      )}
    </header>
  )
}

// ── LANDING ───────────────────────────────────────────────────────

function Landing({ onNav }) {
  const features = [
    ["🔗","Any URL","YouTube, TikTok, Vimeo, Twitter, 1000+ sites"],
    ["🤖","AI Clip Picking","Claude finds the best viral moments automatically"],
    ["🔥","Virality Score","Every clip scored 0–100 so you know what to post first"],
    ["📐","Smart Reframe","Follow-cam crops 9:16 tracking the speaker"],
    ["💬","Styled Subtitles","Word-timed, 6 fonts, custom colours"],
    ["👁️","Face Blur/Track","Auto-detect and blur selected people"],
  ]
  return (
    <div style={{ maxWidth:900, margin:"0 auto", padding:"60px 24px" }}>
      <div style={{ textAlign:"center", marginBottom:64 }}>
        <div style={{ fontSize:48, fontWeight:900, lineHeight:1.1,
                      background:`linear-gradient(135deg,${C.gold},${C.emerald})`,
                      WebkitBackgroundClip:"text", WebkitTextFillColor:"transparent",
                      marginBottom:16 }}>
          Turn Any Video Into<br/>Viral Shorts — Instantly
        </div>
        <p style={{ color:C.dim, fontSize:18, marginBottom:32, maxWidth:540, margin:"0 auto 32px" }}>
          AI picks the best moments, scores their virality, cuts the clips, adds subtitles,
          and reframes for mobile. You just post.
        </p>
        <div style={{ display:"flex", gap:12, justifyContent:"center" }}>
          <button style={{ ...css.btn(C.emerald), fontSize:16, padding:"14px 32px",
                           borderRadius:10 }} onClick={() => onNav("register")}>
            Start Free — 5 Tokens
          </button>
          <button style={{ ...css.btn(C.field, C.text), fontSize:16, padding:"14px 32px",
                           borderRadius:10, border:`1px solid ${C.border}` }}
                  onClick={() => onNav("pricing")}>
            See Pricing
          </button>
        </div>
        <p style={{ color:C.dim, fontSize:12, marginTop:12 }}>No credit card · 0.5 tokens per clip</p>
      </div>

      {/* Virality demo */}
      <div style={{ ...css.card, marginBottom:32, border:`1px solid ${C.emerald}30` }}>
        <div style={css.sec}>🔥 Virality Scoring — Know What to Post</div>
        <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
          {[
            [94, "Mic Drop",        "0:34 – 1:04", "She literally said she'd never do it — then did exactly that"],
            [81, "Relatable Story", "2:12 – 2:42", "The 'I just wanted coffee' spiral that hits too close to home"],
            [63, "Tutorial Gold",   "4:01 – 4:31", "Step-by-step breakdown of the editing process"],
          ].map(([score, tag, time, reason]) => (
            <div key={tag} style={{ display:"flex", alignItems:"center", gap:12,
                                    background:C.field, borderRadius:8, padding:"10px 14px" }}>
              <ViralityBadge score={score} tag={tag} />
              <div style={{ flex:1 }}>
                <div style={{ color:C.text, fontSize:13 }}>{reason}</div>
                <div style={{ color:C.dim, fontSize:11 }}>{time}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:16, marginBottom:48 }}>
        {features.map(([icon,title,desc]) => (
          <div key={title} style={{ ...css.card, textAlign:"center" }}>
            <div style={{ fontSize:32, marginBottom:8 }}>{icon}</div>
            <div style={{ fontWeight:700, color:C.emerald, marginBottom:4 }}>{title}</div>
            <div style={{ color:C.dim, fontSize:13 }}>{desc}</div>
          </div>
        ))}
      </div>

      <div style={{ ...css.card, textAlign:"center",
                    background:"linear-gradient(135deg,#0A0D09,#0D0A04)",
                    border:`1px solid ${C.emerald}40` }}>
        <div style={{ fontSize:24, fontWeight:700, marginBottom:8 }}>
          Ready to 10x your content output?
        </div>
        <p style={{ color:C.dim, marginBottom:20 }}>
          Cheaper than Opus Clip. Faster than editing yourself.
        </p>
        <button style={{ ...css.btn(C.gold, C.dark), fontSize:16,
                         padding:"14px 40px", borderRadius:10 }}
                onClick={() => onNav("register")}>
          Get Started Free
        </button>
      </div>
    </div>
  )
}

// ── PRICING ───────────────────────────────────────────────────────

function Pricing({ token, onNav }) {
  const plans = [
    { id:"free",    label:"Free",    price:"$0",     tokens:5,    period:"on signup",
      clips:"10 clips total", features:["1 video/week","Max 3 clips per job","All features included","Virality scoring"], highlight:false },
    { id:"starter", label:"Starter", price:"$12.99", tokens:100,  period:"/month",
      clips:"200 clips/month", features:["200 clips/month","Unlimited videos","AI clip picking","Smart reframe","Face tracking","Priority queue"], highlight:false },
    { id:"pro",     label:"Pro",     price:"$29.99", tokens:360,  period:"/month",
      clips:"720 clips/month", features:["720 clips/month","Everything in Starter","Bulk processing"], highlight:true },
    { id:"studio",  label:"Studio",  price:"$69.99", tokens:1000, period:"/month",
      clips:"2,000 clips/month", features:["2,000 clips/month","Everything in Pro","Commercial license"], highlight:false },
  ]
  const topups = [
    { id:"small",  label:"20 tokens",  clips:"40 clips",  price:"$4.99" },
    { id:"medium", label:"50 tokens",  clips:"100 clips", price:"$9.99" },
    { id:"large",  label:"140 tokens", clips:"280 clips", price:"$24.99" },
  ]

  const subscribe = async (plan) => {
    if (!token) { onNav("register"); return }
    try {
      const r = await apiFetch("/payments/stripe/subscribe",
        { method:"POST", body:JSON.stringify({plan}) }, token)
      window.location.href = r.checkout_url
    } catch(e) { alert(e.message) }
  }

  return (
    <div style={{ maxWidth:960, margin:"0 auto", padding:"48px 24px" }}>
      <h1 style={{ textAlign:"center", color:C.gold, marginBottom:4,
                  fontFamily:"'Georgia', serif", fontWeight:400, fontSize:36 }}>Pricing</h1>
      <p style={{ textAlign:"center", color:C.dim, marginBottom:8 }}>
        <strong style={{ color:C.gold }}>0.5 tokens per clip</strong> — cheaper than Opus Clip, no compromises
      </p>
      <p style={{ textAlign:"center", color:C.dim, fontSize:13, marginBottom:40 }}>
        Opus Clip charges $19–$49/mo. We charge $12.99–$29.99 for more clips.
      </p>

      <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:16, marginBottom:48 }}>
        {plans.map(p => (
          <div key={p.id} style={{ ...css.card, position:"relative",
            border: p.highlight ? `2px solid ${C.emerald}` : `1px solid ${C.border}` }}>
            {p.highlight && (
              <div style={{ position:"absolute", top:-12, left:"50%", transform:"translateX(-50%)",
                            background:C.emerald, color:C.dark, borderRadius:20,
                            padding:"2px 12px", fontSize:11, fontWeight:700 }}>
                BEST VALUE
              </div>
            )}
            <div style={{ fontWeight:700, fontSize:16, marginBottom:4 }}>{p.label}</div>
            <div style={{ color:C.gold, fontSize:28, fontWeight:900 }}>{p.price}</div>
            <div style={{ color:C.dim, fontSize:12, marginBottom:4 }}>{p.period}</div>
            <div style={{ color:C.emerald, fontWeight:700, marginBottom:4 }}>{p.tokens} tokens</div>
            <div style={{ color:C.gold, fontSize:13, fontWeight:600, marginBottom:12 }}>≈ {p.clips}</div>
            <ul style={{ listStyle:"none", padding:0, margin:"0 0 16px", fontSize:13, color:C.dim }}>
              {p.features.map(f => <li key={f} style={{ padding:"2px 0" }}>✓ {f}</li>)}
            </ul>
            {p.id !== "free" ? (
              <button style={{ ...css.btn(p.highlight ? C.emerald : C.field,
                                          p.highlight ? C.dark : C.text), width:"100%" }}
                      onClick={() => subscribe(p.id)}>
                {token ? "Subscribe" : "Get Started"}
              </button>
            ) : (
              <button style={{ ...css.btn(C.field, C.text), width:"100%" }}
                      onClick={() => onNav("register")}>
                Sign Up Free
              </button>
            )}
          </div>
        ))}
      </div>

      <h2 style={{ color:C.gold, marginBottom:16 }}>Token Top-ups</h2>
      <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:16 }}>
        {topups.map(t => (
          <div key={t.id} style={{ ...css.card, display:"flex",
                                   alignItems:"center", justifyContent:"space-between" }}>
            <div>
              <div style={{ fontWeight:700 }}>{t.label}</div>
              <div style={{ color:C.emerald, fontSize:13 }}>{t.clips}</div>
              <div style={{ color:C.gold, fontSize:22, fontWeight:900 }}>{t.price}</div>
            </div>
            <button style={css.btn(C.gold, C.dark)}
                    onClick={() => token ? null : onNav("register")}>
              Buy
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── AUTH ──────────────────────────────────────────────────────────

function AuthForm({ title, sub, submitLabel, onSubmit, onNav, altText, altPage, altLabel, error }) {
  const [email, setEmail] = useState("")
  const [pass,  setPass]  = useState("")
  const [busy,  setBusy]  = useState(false)
  const go = async () => { setBusy(true); await onSubmit(email,pass).finally(()=>setBusy(false)) }
  return (
    <div style={{ maxWidth:400, margin:"80px auto", padding:"0 24px" }}>
      <div style={css.card}>
        <div style={{ textAlign:"center", marginBottom:24 }}>
          <div style={{ color:C.gold, fontWeight:700, fontSize:18,
                       fontFamily:"'Georgia', serif", letterSpacing:2,
                       textTransform:"uppercase", marginBottom:4 }}>SDP SHORTS</div>
          <h2 style={{ color:C.gold, margin:"8px 0 4px", fontFamily:"'Georgia', serif",
                       fontWeight:400 }}>{title}</h2>
          {sub && <div style={{ color:C.dim, fontSize:13 }}>{sub}</div>}
        </div>
        {error && <div style={{ background:"#FF555520", border:`1px solid ${C.red}`,
                                borderRadius:8, padding:"10px 14px", color:C.red,
                                fontSize:13, marginBottom:16 }}>{error}</div>}
        <label style={css.label}>Email</label>
        <input style={{ ...css.input, marginBottom:12 }} type="email" value={email}
               onChange={e=>setEmail(e.target.value)} onKeyDown={e=>e.key==="Enter"&&go()} />
        <label style={css.label}>Password</label>
        <input style={{ ...css.input, marginBottom:20 }} type="password" value={pass}
               onChange={e=>setPass(e.target.value)} onKeyDown={e=>e.key==="Enter"&&go()} />
        <button style={{ ...css.btn(C.emerald), width:"100%", padding:"12px",
                         fontSize:15, opacity:busy?.6:1 }}
                onClick={go} disabled={busy}>
          {busy ? "…" : submitLabel}
        </button>
        <div style={{ textAlign:"center", marginTop:16, fontSize:13, color:C.dim }}>
          {altText} <span style={{ color:C.emerald, cursor:"pointer" }}
                          onClick={()=>onNav(altPage)}>{altLabel}</span>
        </div>
      </div>
    </div>
  )
}

function Login({ onLogin, onNav }) {
  const [err, setErr] = useState("")
  const go = async (email, pass) => {
    try {
      const r = await apiFetch("/auth/login",{method:"POST",body:JSON.stringify({email,password:pass})})
      onLogin(r.token, {email:r.email,tokens:r.tokens,plan:r.plan,is_admin:r.is_admin||false})
    } catch(e) { setErr(e.message) }
  }
  return (
    <>
      <AuthForm title="Welcome Back" submitLabel="Login" onSubmit={go} onNav={onNav}
                altText="No account?" altPage="register" altLabel="Sign up free" error={err} />
      <div style={{ textAlign:"center", marginTop:-24, paddingBottom:40 }}>
        <span style={{ color:C.dim, fontSize:12, cursor:"pointer", fontFamily:"Arial,sans-serif" }}
              onClick={() => onNav("forgot")}>
          Forgot your password?
        </span>
      </div>
    </>
  )
}

function Register({ onLogin, onNav }) {
  const [err, setErr] = useState("")
  const go = async (email, pass) => {
    try {
      const r = await apiFetch("/auth/register",{method:"POST",body:JSON.stringify({email,password:pass})})
      onLogin(r.token, {email:r.email,tokens:r.tokens,plan:r.plan,is_admin:r.is_admin||false,email_verified:r.email_verified})
      // Show "check your email" nudge (non-blocking — they can still use the app)
      if (!r.email_verified) onNav("check-email")
    } catch(e) { setErr(e.message) }
  }
  return <AuthForm title="Create Account" sub="5 free tokens — no credit card"
                   submitLabel="Sign Up Free" onSubmit={go} onNav={onNav}
                   altText="Have an account?" altPage="login" altLabel="Login" error={err} />
}


// ── CHECK EMAIL PAGE ──────────────────────────────────────────────
function CheckEmail({ onNav }) {
  return (
    <div style={{ maxWidth:440, margin:"80px auto", padding:"0 24px", textAlign:"center" }}>
      <div style={css.card}>
        <div style={{ fontSize:40, marginBottom:16 }}>📬</div>
        <h2 style={{ color:C.gold, fontFamily:"'Georgia',serif", fontWeight:400,
                     marginBottom:12 }}>Check your email</h2>
        <p style={{ color:C.dim, fontSize:14, lineHeight:1.7,
                    fontFamily:"Arial,sans-serif", marginBottom:20 }}>
          We sent a verification link to your email address.<br/>
          Click it to confirm your account and you're all set!
        </p>
        <div style={{ background:C.field, borderRadius:4, padding:"12px 16px",
                      fontSize:12, color:C.dim, fontFamily:"Arial,sans-serif",
                      marginBottom:20, border:`1px solid ${C.border}` }}>
          ℹ️ You can still use the app while waiting — verification just keeps your account secure.
        </div>
        <button style={{ ...css.btn(C.emerald, C.dark), width:"100%", padding:"12px" }}
                onClick={() => onNav("dashboard")}>
          Go to Dashboard
        </button>
      </div>
    </div>
  )
}

// ── VERIFY EMAIL PAGE ─────────────────────────────────────────────
function VerifyEmail({ onNav }) {
  const [status, setStatus] = useState("verifying")
  const [msg,    setMsg]    = useState("")

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("verify")
    if (!token) { setStatus("error"); setMsg("Invalid link"); return }
    apiFetch(`/auth/verify?token=${token}`)
      .then(() => {
        setStatus("success")
        window.history.replaceState({}, "", window.location.pathname)
      })
      .catch(e => { setStatus("error"); setMsg(e.message) })
  }, [])

  return (
    <div style={{ maxWidth:440, margin:"80px auto", padding:"0 24px", textAlign:"center" }}>
      <div style={css.card}>
        {status === "verifying" && (
          <>
            <div style={{ fontSize:36, marginBottom:12 }}>⏳</div>
            <h2 style={{ color:C.gold, fontFamily:"'Georgia',serif", fontWeight:400 }}>Verifying…</h2>
          </>
        )}
        {status === "success" && (
          <>
            <div style={{ fontSize:36, marginBottom:12 }}>✅</div>
            <h2 style={{ color:C.emerald, fontFamily:"'Georgia',serif",
                         fontWeight:400, marginBottom:12 }}>Email verified!</h2>
            <p style={{ color:C.dim, fontSize:14, fontFamily:"Arial,sans-serif",
                        marginBottom:20 }}>
              Your account is confirmed. Welcome to SDP Shorts!
            </p>
            <button style={{ ...css.btn(C.emerald, C.dark), width:"100%", padding:"12px" }}
                    onClick={() => onNav("login")}>Log In</button>
          </>
        )}
        {status === "error" && (
          <>
            <div style={{ fontSize:36, marginBottom:12 }}>❌</div>
            <h2 style={{ color:C.red, fontFamily:"'Georgia',serif",
                         fontWeight:400, marginBottom:12 }}>Link invalid</h2>
            <p style={{ color:C.dim, fontSize:14, fontFamily:"Arial,sans-serif",
                        marginBottom:20 }}>{msg || "This link has expired or already been used."}</p>
            <button style={{ ...css.btn(C.field, C.text), width:"100%", padding:"12px" }}
                    onClick={() => onNav("register")}>Sign up again</button>
          </>
        )}
      </div>
    </div>
  )
}

// ── FORGOT PASSWORD PAGE ──────────────────────────────────────────
function ForgotPassword({ onNav }) {
  const [email,  setEmail]  = useState("")
  const [sent,   setSent]   = useState(false)
  const [busy,   setBusy]   = useState(false)
  const [err,    setErr]    = useState("")

  const go = async () => {
    if (!email.trim()) { setErr("Enter your email address"); return }
    setBusy(true); setErr("")
    try {
      await apiFetch("/auth/forgot", { method:"POST", body:JSON.stringify({email}) })
      setSent(true)
    } catch(e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div style={{ maxWidth:400, margin:"80px auto", padding:"0 24px" }}>
      <div style={css.card}>
        <div style={{ textAlign:"center", marginBottom:24 }}>
          <div style={{ color:C.gold, fontWeight:700, fontSize:18,
                        fontFamily:"'Georgia',serif", letterSpacing:2,
                        textTransform:"uppercase", marginBottom:4 }}>SDP SHORTS</div>
          <h2 style={{ color:C.gold, fontFamily:"'Georgia',serif", fontWeight:400 }}>
            {sent ? "Email sent!" : "Forgot password?"}
          </h2>
        </div>
        {sent ? (
          <>
            <div style={{ textAlign:"center", fontSize:40, marginBottom:12 }}>📬</div>
            <p style={{ color:C.dim, fontSize:14, textAlign:"center", lineHeight:1.7,
                        fontFamily:"Arial,sans-serif", marginBottom:20 }}>
              If that email is registered, we sent a reset link.<br/>Check your inbox!
            </p>
            <button style={{ ...css.btn(C.field, C.text), width:"100%", padding:"12px" }}
                    onClick={() => onNav("login")}>Back to Login</button>
          </>
        ) : (
          <>
            {err && <div style={{ background:"#FF555520", border:`1px solid ${C.red}`,
                                  borderRadius:4, padding:"10px 14px", color:C.red,
                                  fontSize:13, marginBottom:16 }}>{err}</div>}
            <label style={css.label}>Email address</label>
            <input style={{ ...css.input, marginBottom:20 }} type="email" value={email}
                   onChange={e => setEmail(e.target.value)}
                   onKeyDown={e => e.key === "Enter" && go()}
                   placeholder="your@email.com" />
            <button style={{ ...css.btn(C.emerald, C.dark), width:"100%",
                             padding:"12px", opacity:busy?.6:1 }}
                    onClick={go} disabled={busy}>
              {busy ? "Sending…" : "Send Reset Link"}
            </button>
            <div style={{ textAlign:"center", marginTop:16, fontSize:13, color:C.dim }}>
              <span style={{ color:C.emerald, cursor:"pointer" }}
                    onClick={() => onNav("login")}>← Back to Login</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── RESET PASSWORD PAGE ───────────────────────────────────────────
function ResetPassword({ onNav }) {
  const [pass,   setPass]   = useState("")
  const [pass2,  setPass2]  = useState("")
  const [done,   setDone]   = useState(false)
  const [busy,   setBusy]   = useState(false)
  const [err,    setErr]    = useState("")
  const token = new URLSearchParams(window.location.search).get("reset") || ""

  const go = async () => {
    if (pass.length < 8) { setErr("Password must be at least 8 characters"); return }
    if (pass !== pass2)  { setErr("Passwords don't match"); return }
    setBusy(true); setErr("")
    try {
      await apiFetch("/auth/reset", { method:"POST", body:JSON.stringify({token, password:pass}) })
      setDone(true)
      window.history.replaceState({}, "", window.location.pathname)
    } catch(e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div style={{ maxWidth:400, margin:"80px auto", padding:"0 24px" }}>
      <div style={css.card}>
        <div style={{ textAlign:"center", marginBottom:24 }}>
          <div style={{ color:C.gold, fontWeight:700, fontSize:18,
                        fontFamily:"'Georgia',serif", letterSpacing:2,
                        textTransform:"uppercase", marginBottom:4 }}>SDP SHORTS</div>
          <h2 style={{ color:C.gold, fontFamily:"'Georgia',serif", fontWeight:400 }}>
            {done ? "Password updated!" : "Set new password"}
          </h2>
        </div>
        {done ? (
          <>
            <div style={{ textAlign:"center", fontSize:40, marginBottom:12 }}>✅</div>
            <p style={{ color:C.dim, fontSize:14, textAlign:"center",
                        fontFamily:"Arial,sans-serif", marginBottom:20 }}>
              Your password has been reset. Log in with your new password!
            </p>
            <button style={{ ...css.btn(C.emerald, C.dark), width:"100%", padding:"12px" }}
                    onClick={() => onNav("login")}>Log In</button>
          </>
        ) : (
          <>
            {!token && <div style={{ color:C.red, fontSize:13, marginBottom:16,
                                     fontFamily:"Arial,sans-serif" }}>
              ⚠️ Invalid reset link — please request a new one.
            </div>}
            {err && <div style={{ background:"#FF555520", border:`1px solid ${C.red}`,
                                  borderRadius:4, padding:"10px 14px", color:C.red,
                                  fontSize:13, marginBottom:16 }}>{err}</div>}
            <label style={css.label}>New password</label>
            <input style={{ ...css.input, marginBottom:12 }} type="password" value={pass}
                   onChange={e => setPass(e.target.value)} placeholder="At least 8 characters" />
            <label style={css.label}>Confirm new password</label>
            <input style={{ ...css.input, marginBottom:20 }} type="password" value={pass2}
                   onChange={e => setPass2(e.target.value)}
                   onKeyDown={e => e.key === "Enter" && go()} />
            <button style={{ ...css.btn(C.emerald, C.dark), width:"100%",
                             padding:"12px", opacity:busy?.6:1 }}
                    onClick={go} disabled={busy || !token}>
              {busy ? "Updating…" : "Set New Password"}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// ── DASHBOARD ─────────────────────────────────────────────────────

function Dashboard({ user, setUser, token, onNav, onViewClips }) {
  const [jobs,    setJobs]    = useState([])
  const [selJob,  setSelJob]  = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchJobs = useCallback(() => {
    apiFetch("/jobs",{},token).then(setJobs).catch(console.error)
  },[token])

  const retryJob = async (jobId, e) => {
    e.stopPropagation()
    try {
      await apiFetch(`/jobs/${jobId}/retry`, {method:"POST"}, token)
      fetchJobs()
    } catch(err) { alert(err.message) }
  }

  useEffect(() => {
    setLoading(false); fetchJobs()
    const id = setInterval(fetchJobs, 5000)
    return () => clearInterval(id)
  },[fetchJobs])

  const buyTopup = async (pack, provider="stripe") => {
    try {
      if (provider === "stripe") {
        const r = await apiFetch("/payments/stripe/topup",
          {method:"POST",body:JSON.stringify({pack,provider})}, token)
        window.location.href = r.checkout_url
      } else {
        const r = await apiFetch("/payments/paypal/create",
          {method:"POST",body:JSON.stringify({pack,provider})}, token)
        const win = window.open(`https://www.sandbox.paypal.com/checkoutnow?token=${r.order_id}`,
                                "paypal","width=600,height=700")
        const poll = setInterval(async () => {
          if (win.closed) {
            clearInterval(poll)
            try {
              const cap = await apiFetch("/payments/paypal/capture",
                {method:"POST",body:JSON.stringify({order_id:r.order_id,pack})}, token)
              setUser(u => ({...u, tokens:cap.tokens}))
              alert(`✅ Added ${cap.added} tokens!`)
            } catch(e) {}
          }
        },1000)
      }
    } catch(e) { alert(e.message) }
  }

  const sCol = s => ({done:C.emerald,failed:C.red,processing:C.gold,queued:C.dim}[s]||C.dim)

  return (
    <div style={{ maxWidth:960, margin:"0 auto", padding:"32px 24px" }}>
      {/* Stats */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:16, marginBottom:24 }}>
        <div style={css.card}>
          <div style={css.sec}>Token Balance</div>
          <div style={{ fontSize:42, fontWeight:900, color:C.gold }}>
            {user.is_admin ? "∞" : user.tokens}
          </div>
          <div style={{ color:C.dim, fontSize:13 }}>
            {user.is_admin ? "Unlimited clips" : `≈ ${Math.floor(user.tokens / TOKENS_PER_CLIP)} clips remaining`}
          </div>
          {user.next_free_job_at && (
            <div style={{ marginTop:8, color:C.orange, fontSize:12 }}>
              ⏳ Free reset: {new Date(user.next_free_job_at).toLocaleDateString()}
            </div>
          )}
        </div>
        <div style={{ ...css.card, border: user.is_admin ? `1px solid ${C.gold}` : `1px solid ${C.border}` }}>
          <div style={css.sec}>Plan</div>
          {user.is_admin ? (
            <>
              <div style={{ fontSize:22, fontWeight:700, color:C.gold,
                            fontFamily:"'Georgia', serif" }}>Admin</div>
              <div style={{ color:C.emerald, fontSize:13, marginTop:4, fontFamily:"Arial,sans-serif" }}>
                ✓ No token limits
              </div>
              <div style={{ color:C.emerald, fontSize:13, fontFamily:"Arial,sans-serif" }}>
                ✓ No clip limits
              </div>
              <div style={{ color:C.emerald, fontSize:13, fontFamily:"Arial,sans-serif" }}>
                ✓ No weekly restrictions
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize:24, fontWeight:700, color:C.emerald,
                            textTransform:"capitalize" }}>{user.plan}</div>
              {user.plan === "free" && (
                <div style={{ color:C.dim, fontSize:13, marginTop:4 }}>
                  1 video/week · max 3 clips
                </div>
              )}
              <button style={{ ...css.btn(C.field, C.text), marginTop:8, fontSize:12 }}
                      onClick={() => onNav("pricing")}>
                Upgrade →
              </button>
            </>
          )}
        </div>
        {!user.is_admin && (
        <div style={css.card}>
          <div style={css.sec}>Quick Top-up</div>
          <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
            {[["small","40 clips / $4.99"],["medium","100 clips / $9.99"],["large","280 clips / $24.99"]].map(([k,l]) => (
              <div key={k} style={{ display:"flex", gap:6 }}>
                <button style={{ ...css.btn(C.emerald, C.dark), fontSize:11,
                                 padding:"5px 10px", flex:1 }}
                        onClick={() => buyTopup(k,"stripe")}>💳 {l}</button>
                <button style={{ ...css.btn(C.field, C.dim), fontSize:11,
                                 padding:"5px 10px", border:`1px solid ${C.border}` }}
                        onClick={() => buyTopup(k,"paypal")}>🅿️</button>
              </div>
            ))}
          </div>
        </div>
      )}
      </div>

      <div style={{ ...css.card, display:"flex", alignItems:"center",
                    justifyContent:"space-between", marginBottom:24,
                    border:`1px solid ${C.emerald}30` }}>
        <div>
          <div style={{ fontWeight:700, fontSize:16 }}>Create New Shorts</div>
          <div style={{ color:C.dim, fontSize:13 }}>Paste a URL · AI picks the viral moments</div>
        </div>
        <button style={{ ...css.btn(C.emerald), fontSize:15, padding:"12px 28px" }}
                onClick={() => onNav("new")}>⚡ New Job</button>
      </div>

      <div style={css.sec}>Recent Jobs</div>
      {loading ? <div style={{ color:C.dim }}>Loading…</div> :
       jobs.length === 0 ? (
        <div style={{ ...css.card, textAlign:"center", color:C.dim, padding:40 }}>
          No jobs yet — create your first!
        </div>
       ) : (
        <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
          {jobs.map(j => (
            <div key={j.id} style={{ ...css.card, cursor:"pointer" }}
                 onClick={() => setSelJob(selJob?.id===j.id ? null : j)}>
              <div style={{ display:"flex", alignItems:"center", gap:12 }}>
                <div style={{ width:10, height:10, borderRadius:"50%",
                              background:sCol(j.status), flexShrink:0 }}/>
                <div style={{ flex:1, fontSize:14, fontWeight:600 }}>
                  Job {j.id.slice(0,8)}…
                </div>
                <div style={{ color:sCol(j.status), fontSize:12,
                              fontWeight:700, textTransform:"uppercase" }}>{j.status}</div>
                <div style={{ color:C.dim, fontSize:12 }}>{j.clips_count} clips</div>
                {j.status === "done" && j.clips_count > 0 && (
                  <button style={{ ...css.btn(C.gold, C.dark), fontSize:11,
                                   padding:"4px 12px", letterSpacing:1 }}
                          onClick={e => { e.stopPropagation(); onViewClips(j.id) }}>
                    🎬 Pick Clips
                  </button>
                )}
                {(j.status === "queued" || j.status === "failed") && (
                  <button style={{ ...css.btn(C.emerald, C.dark), fontSize:11,
                                   padding:"4px 12px", letterSpacing:1 }}
                          onClick={e => retryJob(j.id, e)}>
                    ▶ Start
                  </button>
                )}
                <div style={{ color:C.dim, fontSize:11 }}>
                  {new Date(j.created_at).toLocaleDateString()}
                </div>
                <div style={{ color:C.dim, fontSize:12 }}>{selJob?.id===j.id ? "▲" : "▼"}</div>
              </div>
              {j.status === "processing" && (
                <div style={{ marginTop:8 }}>
                  <div style={{ display:"flex", justifyContent:"space-between",
                                fontSize:11, color:C.dim, marginBottom:4,
                                fontFamily:"Arial,sans-serif" }}>
                    <span>⚙️ Processing clips…</span>
                    <span style={{ color:C.gold }}>
                      {j.clips_count > 0 ? `${j.clips_count} done` : "Starting…"}
                    </span>
                  </div>
                  <div style={{ height:4, background:C.border, borderRadius:2 }}>
                    <div style={{
                      height:"100%", borderRadius:2,
                      background:`linear-gradient(90deg, ${C.emerald}, ${C.gold})`,
                      width: j.clips_count > 0
                        ? `${Math.min(95, (j.clips_count / (JSON.parse(j.settings||"{}").clip_count||10)) * 100)}%`
                        : "8%",
                      transition:"width 1s ease",
                      animation: j.clips_count === 0 ? "pulse 1.5s infinite" : "none"
                    }}/>
                  </div>
                </div>
              )}
              {j.status === "queued" && (
                <div style={{ marginTop:6, fontSize:11, color:C.dim,
                              fontFamily:"Arial,sans-serif" }}>
                  ⏳ Waiting in queue…
                </div>
              )}

              {selJob?.id === j.id && (
                <div style={{ marginTop:12, borderTop:`1px solid ${C.border}`, paddingTop:12 }}>
                  {j.log && (
                    <pre style={{ background:C.dark, borderRadius:8, padding:12,
                                  fontSize:11, color:C.dim, maxHeight:160,
                                  overflow:"auto", marginBottom:12, whiteSpace:"pre-wrap" }}>
                      {j.log}
                    </pre>
                  )}
                  {j.clips?.length > 0 && (
                    <div>
                      <div style={css.sec}>Download Clips</div>
                      <div style={{ display:"flex", flexWrap:"wrap", gap:8 }}>
                        {j.clips.map(c => (
                          <a key={c.filename} href={`${API}${c.url}`}
                             download={c.filename}
                             style={{ ...css.btn(C.field, C.emerald), textDecoration:"none",
                                      fontSize:12, border:`1px solid ${C.emerald}30` }}>
                            ⬇️ {c.filename.slice(0,28)}…
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
       )}
    </div>
  )
}


// ── CLIP PICKER ───────────────────────────────────────────────────
function ClipPicker({ jobId, token, onNav }) {
  const [job,      setJob]      = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [selected, setSelected] = useState(new Set())
  const [timeLeft, setTimeLeft] = useState("")

  useEffect(() => {
    if (!jobId) { onNav("dashboard"); return }
    apiFetch(`/jobs/${jobId}`, {}, token)
      .then(j => { setJob(j); setLoading(false) })
      .catch(() => { onNav("dashboard") })
  }, [jobId])

  // Countdown timer to expiry
  useEffect(() => {
    if (!job?.expires_at) return
    const tick = () => {
      const diff = new Date(job.expires_at) - new Date()
      if (diff <= 0) { setTimeLeft("Expired"); return }
      const h = Math.floor(diff / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      setTimeLeft(`${h}h ${m}m remaining`)
    }
    tick()
    const id = setInterval(tick, 60000)
    return () => clearInterval(id)
  }, [job])

  if (loading) return (
    <div style={{ textAlign:"center", padding:80, color:C.dim }}>Loading clips…</div>
  )

  // Sort clips by score descending
  const clips = [...(job?.clips || [])].sort((a, b) => (b.score||0) - (a.score||0))
  const scoreCol = s => s >= 85 ? C.emerald : s >= 70 ? C.gold : s >= 55 ? C.orange : C.dim
  const scoreIcon = s => s >= 85 ? "🔥" : s >= 70 ? "⚡" : s >= 55 ? "✨" : "💤"

  const toggleSelect = (fn) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(fn) ? next.delete(fn) : next.add(fn)
      return next
    })
  }

  const selectAll = () => setSelected(new Set(clips.map(c => c.filename)))
  const clearAll  = () => setSelected(new Set())

  const downloadClip = (clip) => {
    const a = document.createElement("a")
    a.href = `${API}${clip.url}`
    a.download = clip.filename
    a.click()
  }

  const downloadSelected = () => {
    clips.filter(c => selected.has(c.filename)).forEach((c, i) => {
      setTimeout(() => downloadClip(c), i * 500)
    })
  }

  return (
    <div style={{ maxWidth:900, margin:"0 auto", padding:"32px 24px" }}>
      {/* Header */}
      <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:24 }}>
        <button style={{ ...css.btn(C.field, C.dim), fontSize:12, padding:"6px 14px" }}
                onClick={() => onNav("dashboard")}>← Dashboard</button>
        <div style={{ flex:1 }}>
          <h2 style={{ color:C.gold, fontFamily:"'Georgia',serif", fontWeight:400,
                       fontSize:24, margin:0 }}>Your Clips</h2>
          <div style={{ color:C.dim, fontSize:12, fontFamily:"Arial,sans-serif", marginTop:2 }}>
            {clips.length} clips · Sorted by virality score
          </div>
        </div>
        {timeLeft && (
          <div style={{ background: timeLeft === "Expired" ? "#CC444420" : "#C9A44315",
                        border: `1px solid ${timeLeft === "Expired" ? C.red : C.gold}40`,
                        borderRadius:4, padding:"6px 14px", fontSize:12,
                        color: timeLeft === "Expired" ? C.red : C.gold,
                        fontFamily:"Arial,sans-serif" }}>
            ⏱ {timeLeft}
          </div>
        )}
      </div>

      {/* Bulk actions */}
      {clips.length > 0 && (
        <div style={{ ...css.card, display:"flex", alignItems:"center", gap:12,
                      marginBottom:20, padding:"14px 20px",
                      border:`1px solid ${C.border}` }}>
          <span style={{ color:C.dim, fontSize:13, fontFamily:"Arial,sans-serif", flex:1 }}>
            {selected.size > 0 ? `${selected.size} clip${selected.size>1?"s":""} selected` : "Select clips to download"}
          </span>
          <button style={{ ...css.btn(C.field, C.dim), fontSize:11, padding:"5px 12px" }}
                  onClick={selectAll}>Select All</button>
          {selected.size > 0 && (
            <>
              <button style={{ ...css.btn(C.field, C.dim), fontSize:11, padding:"5px 12px" }}
                      onClick={clearAll}>Clear</button>
              <button style={{ ...css.btn(C.gold, C.dark), fontSize:11, padding:"5px 16px" }}
                      onClick={downloadSelected}>
                ⬇️ Download {selected.size} Selected
              </button>
            </>
          )}
        </div>
      )}

      {/* Clip cards */}
      {clips.length === 0 ? (
        <div style={{ ...css.card, textAlign:"center", padding:48, color:C.dim }}>
          No clips found for this job.
        </div>
      ) : (
        <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
          {clips.map((clip, idx) => {
            const sel = selected.has(clip.filename)
            const sc  = clip.score || 0
            const col = scoreCol(sc)
            return (
              <div key={clip.filename}
                   onClick={() => toggleSelect(clip.filename)}
                   style={{ ...css.card, cursor:"pointer",
                            border: sel ? `1px solid ${C.gold}` : `1px solid ${C.border}`,
                            background: sel ? "#C9A44308" : C.card,
                            transition:"all .15s" }}>
                <div style={{ display:"flex", alignItems:"center", gap:14 }}>
                  {/* Rank */}
                  <div style={{ color:C.dim, fontSize:13, fontWeight:700,
                                minWidth:20, textAlign:"center",
                                fontFamily:"Arial,sans-serif" }}>
                    #{idx + 1}
                  </div>

                  {/* Score badge */}
                  {sc > 0 && (
                    <div style={{ display:"flex", alignItems:"center", gap:5, flexShrink:0,
                                  background:`${col}18`, border:`1px solid ${col}50`,
                                  borderRadius:20, padding:"4px 12px" }}>
                      <span style={{ fontSize:14 }}>{scoreIcon(sc)}</span>
                      <span style={{ color:col, fontWeight:900, fontSize:16,
                                     fontFamily:"Arial,sans-serif" }}>{sc}</span>
                      {clip.tag && (
                        <span style={{ color:col, fontSize:11, fontWeight:600,
                                       fontFamily:"Arial,sans-serif" }}>{clip.tag}</span>
                      )}
                    </div>
                  )}

                  {/* Hook + time */}
                  <div style={{ flex:1 }}>
                    <div style={{ color:C.text, fontSize:14 }}>
                      {clip.hook || clip.filename.replace(".mp4","").replace(/_/g," ")}
                    </div>
                    {clip.start !== undefined && (
                      <div style={{ color:C.dim, fontSize:11, fontFamily:"Arial,sans-serif",
                                    marginTop:2 }}>
                        {Math.floor(clip.start/60)}:{String(Math.round(clip.start%60)).padStart(2,"0")}
                        {" – "}
                        {Math.floor(clip.end/60)}:{String(Math.round(clip.end%60)).padStart(2,"0")}
                        {" · "}
                        {clip.duration}s
                      </div>
                    )}
                    <div style={{ color:C.dim, fontSize:11, fontFamily:"Arial,sans-serif",
                                  marginTop:2 }}>
                      {clip.filename}
                    </div>
                  </div>

                  {/* Select checkbox */}
                  <div style={{ width:20, height:20, borderRadius:3, flexShrink:0,
                                border:`2px solid ${sel ? C.gold : C.border}`,
                                background: sel ? C.gold : "transparent",
                                display:"flex", alignItems:"center", justifyContent:"center" }}>
                    {sel && <span style={{ color:C.dark, fontSize:13, fontWeight:900 }}>✓</span>}
                  </div>

                  {/* Download single */}
                  <button style={{ ...css.btn(C.emerald, C.dark), fontSize:11,
                                   padding:"6px 14px", flexShrink:0 }}
                          onClick={e => { e.stopPropagation(); downloadClip(clip) }}>
                    ⬇️ Download
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Bottom CTA */}
      {clips.length > 0 && (
        <div style={{ textAlign:"center", marginTop:28, color:C.dim,
                      fontSize:12, fontFamily:"Arial,sans-serif" }}>
          Clips auto-delete 48 hours after processing · Make a new job any time
        </div>
      )}
    </div>
  )
}

// ── NEW JOB ───────────────────────────────────────────────────────

const FONTS    = ["Arial","Impact","Montserrat","Bebas Neue","Anton","Oswald"]
const COLOURS  = ["white","yellow","emerald","gold","red","cyan"]
const LENGTHS  = [15,30,45,60,90]
const FORMATS  = [["both","Both (9:16 + 16:9)"],["vertical","Vertical 9:16"],["original","Original 16:9"]]

function Toggle({ label, hint, value, onChange, colour=C.emerald }) {
  return (
    <div style={{ display:"flex", alignItems:"center", gap:10, padding:"6px 0" }}>
      <div onClick={() => onChange(!value)} style={{
        width:44, height:24, borderRadius:12, background:value?colour:C.field,
        position:"relative", cursor:"pointer", transition:"background .2s",
        border:`1px solid ${value?colour:C.border}`, flexShrink:0
      }}>
        <div style={{ position:"absolute", top:2, left:value?22:2, width:18, height:18,
                      borderRadius:"50%", background:value?C.dark:C.dim, transition:"left .2s" }}/>
      </div>
      <div>
        <div style={{ fontSize:14 }}>{label}</div>
        {hint && <div style={{ fontSize:11, color:C.dim }}>{hint}</div>}
      </div>
    </div>
  )
}

function Sel({ label, value, options, onChange }) {
  return (
    <div style={{ marginBottom:12 }}>
      <label style={css.label}>{label}</label>
      <select value={value} onChange={e=>onChange(e.target.value)}
              style={{ ...css.input, cursor:"pointer" }}>
        {options.map(o => Array.isArray(o)
          ? <option key={o[0]} value={o[0]}>{o[1]}</option>
          : <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  )
}

function NewJob({ user, setUser, token, onNav }) {
  const [url,     setUrl]     = useState("")
  const [count,   setCount]   = useState(user.plan==="free" ? 3 : 10)
  const [length,  setLength]  = useState(30)
  const [format,  setFormat]  = useState("both")
  const [aiPick,  setAiPick]  = useState(true)
  const [subs,    setSubs]    = useState(true)
  const [subFont, setSubFont] = useState("Arial")
  const [subSize, setSubSize] = useState(52)
  const [subCol,  setSubCol]  = useState("white")
  const [reframe, setReframe] = useState(false)
  const [blur,    setBlur]    = useState(false)
  const [audioN,  setAudioN]  = useState(true)
  const [busy,    setBusy]    = useState(false)
  const [err,     setErr]     = useState("")

  const maxClips   = user.is_admin ? 999 : (user.plan === "free" ? 3 : 100)
  const safeCount  = Math.min(count, maxClips)
  const cost       = Math.round(safeCount * TOKENS_PER_CLIP * 10) / 10
  const canAfford  = user.is_admin || user.tokens >= cost

  const submit = async () => {
    if (!url.trim()) { setErr("Paste a video URL first"); return }
    if (!canAfford)  { setErr(`Need ${cost} tokens, you have ${user.tokens}`); return }
    setBusy(true); setErr("")
    try {
      const r = await apiFetch("/jobs", { method:"POST", body:JSON.stringify({
        source_url: url.trim(),
        clip_count: safeCount, clip_length: length,
        output_format: format,
        ai_pick: aiPick, subtitles: subs,
        subtitle_font: subFont, subtitle_size: subSize, subtitle_colour: subCol,
        smart_reframe: reframe, face_blur: blur, audio_norm: audioN,
      })}, token)
      setUser(u => ({...u, tokens:r.tokens_remaining}))
      onNav("dashboard")
    } catch(e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div style={{ maxWidth:700, margin:"0 auto", padding:"32px 24px" }}>
      <h2 style={{ color:C.gold, marginBottom:4, fontFamily:"'Georgia', serif",
                  fontWeight:400, fontSize:28 }}>New Shorts Job</h2>
      <p style={{ color:C.dim, marginBottom:24 }}>Paste a URL · configure · get viral clips</p>

      {err && <div style={{ background:"#FF555520", border:`1px solid ${C.red}`,
                            borderRadius:8, padding:"10px 14px", color:C.red,
                            fontSize:13, marginBottom:16 }}>{err}</div>}

      {/* URL */}
      <div style={{ ...css.card, marginBottom:16 }}>
        <div style={css.sec}>Video URL</div>
        <input style={css.input}
               placeholder="https://youtube.com/watch?v=…  or any video URL"
               value={url} onChange={e=>setUrl(e.target.value)} />
        <div style={{ color:C.dim, fontSize:11, marginTop:6 }}>
          YouTube · TikTok · Vimeo · Twitter · Instagram · 1000+ sites
        </div>
      </div>

      {/* Clip settings */}
      <div style={{ ...css.card, marginBottom:16 }}>
        <div style={css.sec}>Clip Settings</div>
        <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:12, marginBottom:12 }}>
          <div>
            <label style={css.label}>
              Clips {user.plan==="free" && <span style={{ color:C.orange }}>(max 3 free)</span>}
            </label>
            <input style={{ ...css.input, color:C.gold, fontWeight:700, fontSize:20 }}
                   type="number" min={1} max={maxClips} value={count}
                   onChange={e => setCount(Math.min(Number(e.target.value), maxClips))} />
          </div>
          <Sel label="Clip length" value={length}
               options={LENGTHS.map(l=>[l,`${l} sec`])} onChange={v=>setLength(Number(v))} />
          <Sel label="Output format" value={format} options={FORMATS} onChange={setFormat} />
        </div>
        <Toggle label="AI picks best moments + virality scoring" colour={C.gold}
                hint="Claude finds viral moments and scores each 0–100"
                value={aiPick} onChange={setAiPick} />
        <Toggle label="Audio normalization"
                hint="No more volume spikes between clips"
                value={audioN} onChange={setAudioN} />
      </div>

      {/* Subtitles */}
      <div style={{ ...css.card, marginBottom:16 }}>
        <div style={css.sec}>Subtitles</div>
        <Toggle label="Burn in subtitles" hint="Word-timed, styled captions"
                value={subs} onChange={setSubs} />
        {subs && (
          <div style={{ marginTop:12, display:"grid", gridTemplateColumns:"2fr 1fr 1fr", gap:12 }}>
            <Sel label="Font" value={subFont} options={FONTS} onChange={setSubFont} />
            <Sel label="Size" value={subSize}
                 options={[36,44,52,60,72].map(s=>[s,`${s}pt`])} onChange={v=>setSubSize(Number(v))} />
            <Sel label="Colour" value={subCol} options={COLOURS} onChange={setSubCol} />
          </div>
        )}
      </div>

      {/* Face */}
      <div style={{ ...css.card, marginBottom:16 }}>
        <div style={css.sec}>Face Tracking</div>
        <Toggle label="Smart Reframe — follow speaker" colour={C.gold}
                hint="Dynamic 9:16 crop that pans to track the face"
                value={reframe} onChange={setReframe} />
        <Toggle label="Face Blur" hint="Auto-detect and blur all faces"
                value={blur} onChange={setBlur} />
      </div>

      {/* Token Estimator */}
      {user.is_admin ? (
        <div style={{ marginBottom:16, background:"#C9A44315",
                      border:`1px solid ${C.gold}40`, borderRadius:4,
                      padding:"14px 16px", fontFamily:"Arial,sans-serif" }}>
          <div style={{ color:C.gold, fontWeight:700, fontSize:12,
                        letterSpacing:2, textTransform:"uppercase", marginBottom:4 }}>
            ★ Admin Access
          </div>
          <div style={{ color:C.dim, fontSize:13 }}>
            No tokens will be deducted · No clip limits · No restrictions
          </div>
        </div>
      ) : (
        <div style={{ marginBottom:16 }}>
          <TokenEstimator clipCount={safeCount} userTokens={user.tokens}
                          plan={user.plan} nextFreeJobAt={user.next_free_job_at} />
        </div>
      )}

      {/* Submit */}
      <div style={{ display:"flex", gap:12 }}>
        {!canAfford && (
          <button style={{ ...css.btn(C.gold, C.dark), flex:1, padding:"14px" }}
                  onClick={() => onNav("pricing")}>Buy Tokens</button>
        )}
        <button style={{ ...css.btn(canAfford?C.emerald:C.field, canAfford?C.dark:C.dim),
                         flex:2, padding:"14px", fontSize:16,
                         opacity:busy?.6:1 }}
                onClick={submit} disabled={!canAfford||busy}>
          {busy ? "Starting job…" : `⚡ Make ${safeCount} Shorts (${cost} tokens)`}
        </button>
      </div>
    </div>
  )
}
