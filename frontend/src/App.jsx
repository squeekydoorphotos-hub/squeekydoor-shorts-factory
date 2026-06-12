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

// ââ API ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
function apiFetch(path, opts={}, token=null) {
  const headers = { "Content-Type":"application/json", ...(opts.headers||{}) }
  if (token) headers["Authorization"] = `Bearer ${token}`
  return fetch(API + path, { ...opts, headers, credentials: 'include' })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.detail || "Error") }))
}

async function downloadWithAuth(url, filename, token) {
  const res = await fetch(url, {
    headers: { "Authorization": `Bearer ${token}` }, credentials: 'include'
  })
  const blob = await res.blob()
  const blobUrl = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(blobUrl)
}

// ââ VIDEO PREVIEW MODAL ââââââââââââââââââââââââââââââââââââââââââ

function VideoPreview({ url, token, filename, onClose }) {
  const [blobUrl, setBlobUrl] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err,     setErr]     = useState("")
  useEffect(() => {
    let obj = null
    fetch(url, { headers: { Authorization: `Bearer ${token}` }, credentials: 'include' })
      .then(r => { if (!r.ok) throw new Error("Failed to load clip"); return r.blob() })
      .then(b => { obj = URL.createObjectURL(b); setBlobUrl(obj); setLoading(false) })
      .catch(e => { setErr(e.message); setLoading(false) })
    return () => { if (obj) URL.revokeObjectURL(obj) }
  }, [url, token])
  return (
    <div onClick={onClose} style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.92)", zIndex:9999, display:"flex", alignItems:"center", justifyContent:"center" }}>
      <div onClick={e => e.stopPropagation()} style={{ background:C.card, borderRadius:12, padding:20, maxWidth:520, width:"92%", border:`1px solid ${C.border}` }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:12 }}>
          <div style={{ fontSize:12, color:C.dim, fontFamily:"monospace", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", maxWidth:400 }}>{filename}</div>
          <button onClick={onClose} style={{ ...css.btn(C.field, C.dim), padding:"4px 10px", fontSize:16 }}>â</button>
        </div>
        {loading && <div style={{ textAlign:"center", padding:40, color:C.dim }}>â³ Loading previewâ¦</div>}
        {err     && <div style={{ color:C.red, padding:20, textAlign:"center" }}>{err}</div>}
        {blobUrl && <video controls autoPlay style={{ width:"100%", borderRadius:8, background:"#000", maxHeight:520 }} src={blobUrl} />}
        <div style={{ display:"flex", gap:8, marginTop:12 }}>
          <button style={{ ...css.btn(C.emerald, C.dark), flex:1, opacity:blobUrl?1:0.4, pointerEvents:blobUrl?"auto":"none" }}
                  onClick={() => { if(blobUrl){const a=document.createElement("a");a.href=blobUrl;a.download=filename;a.click()} }}>
            â¬ï¸ Download
          </button>
          <button onClick={onClose} style={{ ...css.btn(C.field, C.dim), flex:1 }}>Close</button>
        </div>
      </div>
    </div>
  )
}

// ââ VIRALITY SCORE badge âââââââââââââââââââââââââââââââââââââââââââ
function ViralityBadge({ score, tag }) {
  if (!score && score !== 0) return null
  const colour = score >= 85 ? C.emerald : score >= 70 ? C.gold :
                 score >= 55 ? C.orange  : C.dim
  const fire   = score >= 85 ? "ð¥" : score >= 70 ? "â¡" :
                 score >= 55 ? "â¨" : "ð¤"
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

// ââ TOKEN ESTIMATOR ââââââââââââââââââââââââââââââââââââââââââââââââ
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
          â{cost} tokens
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
          â³ {freeMsg}
        </div>
      )}
      {!canDo && (
        <div style={{ marginTop:10, background:"#FF555520", border:`1px solid ${C.red}40`,
                      borderRadius:8, padding:"8px 12px", color:C.red, fontSize:12 }}>
          Not enough tokens â buy a top-up or upgrade your plan
        </div>
      )}
    </div>
  )
}

// âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
//  TOP-LEVEL APP
// ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

export default function App() {
  const [token,       setToken]       = useState("")
  const [user,        setUser]        = useState(null)
  const [page,        setPage]        = useState("landing")
  const [selectedJob, setSelectedJob] = useState(null)

  const login = (tok, userData) => {
    setToken(tok); setUser(userData); setPage("dashboard")
  }
  const logout = () => {
    fetch(`${API}/auth/logout`, { method: "POST", credentials: "include" }).catch(() => {})
    setToken(""); setUser(null); setPage("landing")
  }

  useEffect(() => {
    // Restore session from httpOnly cookie (no localStorage)
    apiFetch("/auth/me", {}, null)
      .then(u => { if (u && u.email) { if (u.token) setToken(u.token); setUser(u); setPage("dashboard") } })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const p = new URLSearchParams(window.location.search)
    if (p.get("sub") === "success" || p.get("topup") === "success") {
      apiFetch("/auth/me", {}, token).then(u => { setUser(u); if (u.token) setToken(u.token) })
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
    // Direct links to policy pages
    const path = window.location.pathname
    if (path === "/privacy") setPage("privacy")
    if (path === "/terms")   setPage("terms")
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
      {page==="access"    && user && user.email==="layzphotos@gmail.com" && <ManageAccess token={token} onNav={setPage} />}
      {page==="new"       && user && <NewJob    user={user} setUser={setUser} token={token} onNav={setPage} />}
      {page==="verify"    && <VerifyEmail onNav={setPage} />}
      {page==="clips"     && <ClipPicker jobId={selectedJob} token={token} onNav={setPage} />}
      {page==="forgot"    && <ForgotPassword onNav={setPage} />}
      {page==="reset"     && <ResetPassword onNav={setPage} />}
      {page==="check-email" && <CheckEmail onNav={setPage} />}
      {page==="privacy"   && <PrivacyPolicy />}
      {page==="terms"     && <TermsOfService />}
      <Footer onNav={setPage} />
    </div>
  )
}

// ââ HEADER ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

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
              â ADMIN Â· NO LIMITS
            </div>
          )}
          <div style={{ background:C.field, borderRadius:20, padding:"4px 14px",
                        fontSize:13, color:C.gold, fontWeight:700, displsplay:"flex",
                        alignItems:"center", gap:6 }}>
            â¡ {user.is_admin ? "â" : user.tokens} tokens
          </div>
          <button style={css.btn(C.emerald)} onClick={() => onNav("new")}>+ New Job</button>
          {user.email==="layzphotos@gmail.com" && <button style={css.btn(C.field, C.gold)} onClick={() => onNav("access")}>Manage Access</button>}
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

// ââ LANDING âââââââââââââââââââââââââââââââââââââââââââââââââââââââ

function Landing({ onNav }) {
  const features = [
    ["ð","Any URL","YouTube, TikTok, Vimeo, Twitter, 1000+ sites"],
    ["ð¤","AI Clip Picking","Claude finds the best viral moments automatically"],
    ["ð¥","Virality Score","Every clip scored 0â100 so you know what to post first"],
    ["ð","Smart Reframe","Follow-cam crops 9:16 tracking the speaker"],
    ["ð¬","Styled Subtitles","Word-timed, 6 fonts, custom colours"],
    ["ðï¸","Face Blur/Track","Auto-detect and blur selected people"],
  ]
  return (
    <div style={{ maxWidth:900, margin:"0 auto", padding:"60px 24px" }}>
      <div style={{ textAlign:"center", marginBottom:64 }}>
        <div style={{ fontSize:48, fontWeight:900, lineHeight:1.1,
                      background:`linear-gradient(135deg,${C.gold},${C.emerald})`,
                      WebkitBackgroundClip:"text", WebkitTextFillColor:"transparent",
                      marginBottom:16 }}>
          Turn Any Video Into<br/>Viral Shorts â Instantly
        </div>
        <p style={{ color:C.dim, fontSize:18, marginBottom:32, maxWidth:540, margin:"0 auto 32px" }}>
          AI picks the best moments, scores their virality, cuts the clips, adds subtitles,
          and reframes for mobile. You just post.
        </p>
        <div style={{ display:"flex", gap:12, justifyContent:"center" }}>
          <button style={{ ...css.btn(C.emerald), fontSize:16, padding:"14px 32px",
                           borderRadius:10 }} onClick={() => onNav("register")}>
            Start Free â 5 Tokens
          </button>
          <button style={{ ...css.btn(C.field, C.text), fontSize:16, padding:"14px 32px",
                           borderRadius:10, border:`1px solid ${C.border}` }}
                  onClick={() => onNav("pricing")}>
            See Pricing
          </button>
        </div>
        <p style={{ color:C.dim, fontSize:12, marginTop:12 }}>No credit card Â· 0.5 tokens per clip</p>
      </div>

      {/* Virality demo */}
      <div style={{ ...css.card, marginBottom:32, border:`1px solid ${C.emerald}30` }}>
        <div style={css.sec}>ð¥ Virality Scoring â Know What to Post</div>
        <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
          {[
            [94, "Mic Drop",        "0:34 â 1:04", "She literally said she'd never do it â then did exactly that"],
            [81, "Relatable Story", "2:12 â 2:42", "The 'I just wanted coffee' spiral that hits too close to home"],
            [63, "Tutorial Gold",   "4:01 â 4:31", "Step-by-step breakdown of the editing process"],
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

// ââ PRICING âââââââââââââââââââââââââââââââââââââââââââââââââââââââ

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
        <strong style={{ color:C.gold }}>0.5 tokens per clip</strong> â cheaper than Opus Clip, no compromises
      </p>
      <p style={{ textAlign:"center", color:C.dim, fontSize:13, marginBottom:40 }}>
        Opus Clip charges $19â$49/mo. We charge $12.99â$29.99 for more clips.
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
            <div style={{ color:C.gold, fontSize:13, fontWeight:600, marginBottom:12 }}>â {p.clips}</div>
            <ul style={{ listStyle:"none", padding:0, margin:"0 0 16px", fontSize:13, color:C.dim }}>
              {p.features.map(f => <li key={f} style={{ padding:"2px 0" }}>â {f}</li>)}
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

// ââ AUTH ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

function AuthForm({ title, sub, submitLabel, onSubmit, onNav, altText, altPage, altLabel, error, note }) {
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
        {note && <div style={{ fontSize:11.5, color:C.dim, marginBottom:14,
                                textAlign:"center", lineHeight:1.5 }}>{note}</div>}
        <button style={{ ...css.btn(C.emerald), width:"100%", padding:"12px",
                         fontSize:15, opacity:busy?.6:1 }}
                onClick={go} disabled={busy}>
          {busy ? "â¦" : submitLabel}
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
      onLogin(r.token, {email:r.email,tokens:r.tokens,plan:r.plan,is_admin:r.is_admin||false,can_connect_socials:r.can_connect_socials||false})
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
      onLogin(r.token, {email:r.email,tokens:r.tokens,plan:r.plan,is_admin:r.is_admin||false,can_connect_socials:r.can_connect_socials||false,email_verified:r.email_verified})
      // Show "check your email" nudge (non-blocking â they can still use the app)
      if (!r.email_verified) onNav("check-email")
    } catch(e) { setErr(e.message) }
  }
  return <AuthForm title="Create Account" sub="5 free tokens â no credit card"
                   submitLabel="Sign Up Free" onSubmit={go} onNav={onNav}
                   altText="Have an account?" altPage="login" altLabel="Login" error={err}
                   note={<>By creating an account you agree to our{" "}
                     <span style={{ color:C.emerald, cursor:"pointer" }} onClick={()=>onNav("terms")}>Terms of Service</span>{" "}and{" "}
                     <span style={{ color:C.emerald, cursor:"pointer" }} onClick={()=>onNav("privacy")}>Privacy Policy</span>.</>} />
}


// ââ CHECK EMAIL PAGE ââââââââââââââââââââââââââââââââââââââââââââââ
function CheckEmail({ onNav }) {
  return (
    <div style={{ maxWidth:440, margin:"80px auto", padding:"0 24px", textAlign:"center" }}>
      <div style={css.card}>
        <div style={{ fontSize:40, marginBottom:16 }}>ð¬</div>
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
          â¹ï¸ You can still use the app while waiting â verification just keeps your account secure.
        </div>
        <button style={{ ...css.btn(C.emerald, C.dark), width:"100%", padding:"12px" }}
                onClick={() => onNav("dashboard")}>
          Go to Dashboard
        </button>
      </div>
    </div>
  )
}

// ââ VERIFY EMAIL PAGE âââââââââââââââââââââââââââââââââââââââââââââ
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
            <div style={{ fontSize:36, marginBottom:12 }}>â³</div>
            <h2 style={{ color:C.gold, fontFamily:"'Georgia',serif", fontWeight:400 }}>Verifyingâ¦</h2>
          </>
        )}
        {status === "success" && (
          <>
            <div style={{ fontSize:36, marginBottom:12 }}>â</div>
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
            <div style={{ fontSize:36, marginBottom:12 }}>â</div>
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

// ââ FORGOT PASSWORD PAGE ââââââââââââââââââââââââââââââââââââââââââ
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
            <div style={{ textAlign:"center", fontSize:40, marginBottom:12 }}>ð¬</div>
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
              {busy ? "Sendingâ¦" : "Send Reset Link"}
            </button>
            <div style={{ textAlign:"center", marginTop:16, fontSize:13, color:C.dim }}>
              <span style={{ color:C.emerald, cursor:"pointer" }}
                    onClick={() => onNav("login")}>â Back to Login</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ââ RESET PASSWORD PAGE âââââââââââââââââââââââââââââââââââââââââââ
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
            <div style={{ textAlign:"center", fontSize:40, marginBottom:12 }}>â</div>
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
              â ï¸ Invalid reset link â please request a new one.
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
              {busy ? "Updatingâ¦" : "Set New Password"}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// ââ DASHBOARD âââââââââââââââââââââââââââââââââââââââââââââââââââââ

function Dashboard({ user, setUser, token, onNav, onViewClips }) {
  const [jobs,    setJobs]    = useState([])
  const [selJob,  setSelJob]  = useState(null)
  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState(null)

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
              alert(`â Added ${cap.added} tokens!`)
            } catch(e) {}
          }
        },1000)
      }
    } catch(e) { alert(e.message) }
  }

  const sCol = s => ({done:C.emerald,failed:C.red,processing:C.gold,queued:C.dim}[s]||C.dim)

  return (
    <div style={{ maxWidth:960, margin:"0 auto", padding:"32px 24px" }}>
      {preview && <VideoPreview url={preview.url} token={token} filename={preview.filename} onClose={() => setPreview(null)} />}
      {/* Stats */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:16, marginBottom:24 }}>
        <div style={css.card}>
          <div style={css.sec}>Token Balance</div>
          <div style={{ fontSize:42, fontWeight:900, color:C.gold }}>
            {user.is_admin ? "â" : user.tokens}
          </div>
          <div style={{ color:C.dim, fontSize:13 }}>
            {user.is_admin ? "Unlimited clips" : `â ${Math.floor(user.tokens / TOKENS_PER_CLIP)} clips remaining`}
          </div>
          {user.next_free_job_at && (
            <div style={{ marginTop:8, color:C.orange, fontSize:12 }}>
              â³ Free reset: {new Date(user.next_free_job_at).toLocaleDateString()}
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
                â No token limits
              </div>
              <div style={{ color:C.emerald, fontSize:13, fontFamily:"Arial,sans-serif" }}>
                â No clip limits
              </div>
              <div style={{ color:C.emerald, fontSize:13, fontFamily:"Arial,sans-serif" }}>
                â No weekly restrictions
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize:24, fontWeight:700, color:C.emerald,
                            textTransform:"capitalize" }}>{user.plan}</div>
              {user.plan === "free" && (
                <div style={{ color:C.dim, fontSize:13, marginTop:4 }}>
                  1 video/week Â· max 3 clips
                </div>
              )}
              <button style={{ ...css.btn(C.field, C.text), marginTop:8, fontSize:12 }}
                      onClick={() => onNav("pricing")}>
                Upgrade â
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
                        onClick={() => buyTopup(k,"stripe")}>ð³ {l}</button>
                <button style={{ ...css.btn(C.field, C.dim), fontSize:11,
                                 padding:"5px 10px", border:`1px solid ${C.border}` }}
                        onClick={() => buyTopup(k,"paypal")}>ð¿ï¸</button>
              </div>
            ))}
          </div>
        </div>
      )}
      </div>

      {user.can_connect_socials && (
      <div style={{ ...css.card, marginBottom:24, border:`1px solid ${C.emerald}30` }}>
        <div style={css.sec}>Social Accounts</div>
        <div style={{ color:C.dim, fontSize:13, marginBottom:12 }}>
          Connect your own social accounts to schedule and track posts.
        </div>
        <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
          {["YouTube","TikTok","Instagram","Facebook"].map(p => (
            <button key={p} style={{ ...css.btn(C.field, C.text), fontSize:13 }}
                    onClick={() => {
                      if (p === "YouTube") {
                        fetch(`https://backend-production-33b3.up.railway.app/social/youtube/auth`, {headers:{Authorization:`Bearer ${token}`}})
                          .then(r => r.json())
                          .then(d => {
                            if (d.auth_url) {
                              const popup = window.open(d.auth_url, 'yt_auth', 'width=600,height=700');
                              const timer = setInterval(() => {
                                if (popup && popup.closed) {
                                  clearInterval(timer);
                                  apiFetch('/social/youtube/status', {}, token)
                                    .then(r => setYtConn(r.connected))
                                    .catch(() => {});
                                }
                              }, 1000);
                            }
                          })
                          .catch(() => alert('YouTube connection failed â try again'));
                      } else {
                        alert(`Connect ${p} â coming soon!`)
                      }
                    }}>
              ð Connect {p}
            </button>
          ))}
        </div>
      </div>
      )}

      <div style={{ ...css.card, display:"flex", alignItems:"center",
                    justifyContent:"space-between", marginBottom:24,
                    border:`1px solid ${C.emerald}30` }}>
        <div>
          <div style={{ fontWeight:700, fontSize:16 }}>Create New Shorts</div>
          <div style={{ color:C.dim, fontSize:13 }}>Paste a URL Â· AI picks the viral moments</div>
        </div>
        <button style={{ ...css.btn(C.emerald), fontSize:15, padding:"12px 28px" }}
                onClick={() => onNav("new")}>â¡ New Job</button>
      </div>

      <div style={css.sec}>Recent Jobs</div>
      {loading ? <div style={{ color:C.dim }}>Loadingâ¦</div> :
       jobs.length === 0 ? (
        <div style={{ ...css.card, textAlign:"center", color:C.dim, padding:40 }}>
          No jobs yet â create your first!
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
                  Job {j.id.slice(0,8)}â¦
                </div>
                <div style={{ color:sCol(j.status), fontSize:12,
                              fontWeight:700, textTransform:"uppercase" }}>{j.status}</div>
                <div style={{ color:C.dim, fontSize:12 }}>{j.clips_count} clips</div>
                {j.status === "done" && j.clips_count > 0 && (
                  <button style={{ ...css.btn(C.gold, C.dark), fontSize:11,
                                   padding:"4px 12px", letterSpacing:1 }}
                          onClick={e => { e.stopPropagation(); onViewClips(j.id) }}>
                    ð¬ Pick Clips
                  </button>
                )}
                {(j.status === "queued" || j.status === "failed") && (
                  <button style={{ ...css.btn(C.emerald, C.dark), fontSize:11,
                                   padding:"4px 12px", letterSpacing:1 }}
                          onClick={e => retryJob(j.id, e)}>
                    â¶ Start
                  </button>
                )}
                <div style={{ color:C.dim, fontSize:11 }}>
                  {new Date(j.created_at).toLocaleDateString()}
                </div>
                <div style={{ color:C.dim, fontSize:12 }}>{selJob?.id===j.id ? "â²" : "â¼"}</div>
              </div>
              {j.status === "processing" && (
                <div style={{ marginTop:8 }}>
                  <div style={{ display:"flex", justifyContent:"space-between",
                                fontSize:11, color:C.dim, marginBottom:4,
                                fontFamily:"Arial,sans-serif" }}>
                    <span>âï¸ Processing clipsâ¦</span>
                    <span style={{ color:C.gold }}>
                      {j.clips_count > 0 ? `${j.clips_count} done` : "Startingâ¦"}
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
                  â³ Waiting in queueâ¦
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
                          <div key={c.filename} style={{ display:"flex", gap:6 }}>
                            <button onClick={() => setPreview({url:`${API}${c.url}`, filename:c.filename})}
                                    style={{ ...css.btn(C.field, C.gold), fontSize:12, border:`1px solid ${C.gold}40` }}>
                              â¶ Preview
                            </button>
                            <button onClick={() => downloadWithAuth(`${API}${c.url}`, c.filename, token)}
                                    style={{ ...css.btn(C.field, C.emerald), fontSize:12, border:`1px solid ${C.emerald}30` }}>
                              â¬ï¸ {c.filename.slice(0,28)}â¦
                            </button>
                          </div>
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


// ââ CLIP PICKER âââââââââââââââââââââââââââââââââââââââââââââââââââ
function ClipPicker({ jobId, token, onNav }) {
  const [job,      setJob]      = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [selected,     setSelected]     = useState(new Set())
  const [pickerPreview, setPickerPreview] = useState(null)
  const [timeLeft, setTimeLeft] = useState("")
  const [ytConn,  setYtConn]  = useState(false)
  const [ytModal, setYtModal] = useState(null)
  const [ytTitle, setYtTitle] = useState("")
  const [ytDesc,  setYtDesc]  = useState("")
  const [ytAt,    setYtAt]    = useState("")
  const [ytBusy,  setYtBusy]  = useState(false)
  const [ytMsg,   setYtMsg]   = useState("")

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

  useEffect(() => {
    apiFetch("/social/youtube/status", {}, token)
      .then(r => setYtConn(r.connected))
      .catch(() => {})
  }, [token])

  if (loading) return (
    <div style={{ textAlign:"center", padding:80, color:C.dim }}>Loading clipsâ¦</div>
  )

  // Sort clips by score descending
  const clips = [...(job?.clips || [])].sort((a, b) => (b.score||0) - (a.score||0))
  const scoreCol = s => s >= 85 ? C.emerald : s >= 70 ? C.gold : s >= 55 ? C.orange : C.dim
  const scoreIcon = s => s >= 85 ? "ð¥" : s >= 70 ? "â¡" : s >= 55 ? "â¨" : "ð¤"

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
    downloadWithAuth(`${API}${clip.url}`, clip.hook ? clip.hook.replace(/[^a-zA-Z0-9 ]/g,'').trim().replace(/ +/g,'_').slice(0,80)+'.mp4' : clip.filename, token)
  }

  const downloadSelected = () => {
    clips.filter(c => selected.has(c.filename)).forEach((c, i) => {
      setTimeout(() => downloadClip(c), i * 500)
    })
  }

  const uploadToYt = async () => {
    if (!ytModal) return
    setYtBusy(true); setYtMsg("")
    try {
      const ps = new URLSearchParams({
        clip_job_id: job && job.id,
        clip_filename: ytModal.filename,
        title: ytTitle,
        description: ytDesc,
        publish_at: ytAt ? new Date(ytAt).toISOString() : "",
      })
      const r = await apiFetch("/social/youtube/upload?" + ps, {method:"POST"}, token)
      setYtMsg("â Uploaded! " + (r.youtube_url||""))
      setYtBusy(false)
    } catch(e) {
      setYtMsg("â " + e.message)
      setYtBusy(false)
    }
  }

  return (
    <div style={{ maxWidth:900, margin:"0 auto", padding:"32px 24px" }}>
      {/* Header */}
      <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:24 }}>
        <button style={{ ...css.btn(C.field, C.dim), fontSize:12, padding:"6px 14px" }}
                onClick={() => onNav("dashboard")}>â Dashboard</button>
        <div style={{ flex:1 }}>
          <h2 style={{ color:C.gold, fontFamily:"'Georgia',serif", fontWeight:400,
                       fontSize:24, margin:0 }}>Your Clips</h2>
          <div style={{ color:C.dim, fontSize:12, fontFamily:"Arial,sans-serif", marginTop:2 }}>
            {clips.length} clips Â· Sorted by virality score
          </div>
        </div>
        {timeLeft && (
          <div style={{ background: timeLeft === "Expired" ? "#CC444420" : "#C9A44315",
                        border: `1px solid ${timeLeft === "Expired" ? C.red : C.gold}40`,
                        borderRadius:4, padding:"6px 14px", fontSize:12,
                        color: timeLeft === "Expired" ? C.red : C.gold,
                        fontFamily:"Arial,sans-serif" }}>
            â± {timeLeft}
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
                â¬ï¸ Download {selected.size} Selected
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

                  {/* Title + time */}
                  <div style={{ flex:1 }}>
                    <div style={{ color:C.text, fontSize:16, fontWeight:700,
                                  lineHeight:1.3, marginBottom:4,
                                  fontFamily:"'Segoe UI', Arial, sans-serif" }}>
                      {clip.hook || clip.filename.replace(".mp4","").replace(/_/g," ")}
                    </div>
                    {clip.start !== undefined && (
                      <div style={{ color:C.dim, fontSize:11, fontFamily:"Arial,sans-serif",
                                    marginTop:2 }}>
                        {Math.floor(clip.start/60)}:{String(Math.round(clip.start%60)).padStart(2,"0")}
                        {" â "}
                        {Math.floor(clip.end/60)}:{String(Math.round(clip.end%60)).padStart(2,"0")}
                        {" Â· "}
                        {clip.duration}s
                      </div>
                    )}
                    <div style={{ color:C.dim, fontSize:10, fontFamily:"Arial,sans-serif",
                                  marginTop:2, opacity:0.6 }}>
                      {clip.filename}
                    </div>
                  </div>

                  {/* Select checkbox */}
                  <div style={{ width:20, height:20, borderRadius:3, flexShrink:0,
                                border:`2px solid ${sel ? C.gold : C.border}`,
                                background: sel ? C.gold : "transparent",
                                display:"flex", alignItems:"center", justifyContent:"center" }}>
                    {sel && <span style={{ color:C.dark, fontSize:13, fontWeight:900 }}>â</span>}
                  </div>

                  {/* Preview + Download */}
                  <button style={{ ...css.btn(C.field, C.gold), fontSize:11, padding:"6px 14px", flexShrink:0, border:`1px solid ${C.gold}40` }}
                          onClick={e => { e.stopPropagation(); setPickerPreview({url:`${API}${clip.url}`, filename:clip.filename}) }}>
                    â¶
                  </button>
                  <button style={{ ...css.btn(C.emerald, C.dark), fontSize:11, padding:"6px 14px", flexShrink:0 }}
                          onClick={e => { e.stopPropagation(); downloadClip(clip) }}>
                    â¬ï¸ Download
                  </button>
                {ytConn && (
                  <button style={{ ...css.btn(C.red, C.dark), fontSize:11, padding:"6px 14px", flexShrink:0, marginLeft:6 }}
                          onClick={e => { e.stopPropagation(); setYtModal(clip); setYtTitle(clip.hook||""); setYtDesc(""); setYtAt("") }}>
                    â¶ï¸ YouTube
                  </button>
                )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {pickerPreview && <VideoPreview url={pickerPreview.url} token={token} filename={pickerPreview.filename} onClose={() => setPickerPreview(null)} />}

      {pickerPreview && <VideoPreview url={pickerPreview.url} token={token} filename={pickerPreview.filename} onClose={() => setPickerPreview(null)} />}

      {/* Bottom CTA */}
      {clips.length > 0 && (
        <div style={{ textAlign:"center", marginTop:28, color:C.dim,
                      fontSize:12, fontFamily:"Arial,sans-serif" }}>
          Clips auto-delete 48 hours after processing Â· Make a new job any time
        </div>
      )}

      {ytModal && (
        <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,.75)",display:"flex",alignItems:"center",justifyContent:"center",zIndex:999}} onClick={()=>{setYtModal(null);setYtMsg("")}}>
          <div style={{background:C.card,border:"1px solid "+C.border,borderRadius:12,padding:"28px 32px",width:"100%",maxWidth:480,display:"flex",flexDirection:"column",gap:14}} onClick={e=>e.stopPropagation()}>
            <div style={{fontWeight:700,fontSize:18,color:C.text}}>â¶ï¸ Post to YouTube</div>
            <div style={{color:C.muted,fontSize:12}}>Clip: {ytModal.filename}</div>
            <input placeholder="Title *" value={ytTitle} onChange={e=>setYtTitle(e.target.value)}
                   style={{background:C.dark,border:"1px solid "+C.border,borderRadius:6,padding:"8px 12px",color:C.text,fontSize:13,outline:"none"}} />
            <textarea placeholder="Description (optional)" value={ytDesc} onChange={e=>setYtDesc(e.target.value)} rows={3}
                      style={{background:C.dark,border:"1px solid "+C.border,borderRadius:6,padding:"8px 12px",color:C.text,fontSize:13,resize:"vertical",outline:"none"}} />
            <div style={{display:"flex",flexDirection:"column",gap:4}}>
              <label style={{fontSize:11,color:C.dim,letterSpacing:1,textTransform:"uppercase"}}>Schedule (blank = post now)</label>
              <input type="datetime-local" value={ytAt} onChange={e=>setYtAt(e.target.value)}
                   style={{background:C.dark,border:"1px solid "+C.border,borderRadius:6,padding:"8px 12px",color:C.text,fontSize:13,outline:"none",colorScheme:"dark"}} />
            </div>
            {ytMsg && <div style={{fontSize:13,color:ytMsg.startsWith("â")?C.emerald:"#ef4444"}}>{ytMsg}</div>}
            <div style={{display:"flex",gap:10,justifyContent:"flex-end"}}>
              <button style={css.btn(C.muted,C.dark)} onClick={()=>{setYtModal(null);setYtMsg("")}}>Cancel</button>
              <button style={{...css.btn(C.red,C.dark),opacity:ytBusy||!ytTitle?0.5:1}} disabled={ytBusy||!ytTitle} onClick={uploadToYt}>{ytBusy?"Uploadingâ¦":"Upload"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ââ NEW JOB âââââââââââââââââââââââââââââââââââââââââââââââââââââââ

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

  const maxClips   = user.is_admin ? 500 : (user.plan === "free" ? 3 : user.plan === "studio" ? 500 : user.plan === "pro" ? 200 : 100)
  const safeCount  = Math.min(count, maxClips)
  const cost       = Math.round(safeCount * TOKENS_PER_CLIP * 10) / 10
  const canAfford  = user.is_admin || user.tokens >= cost

  const submit = async () => {
    if (!url.trim()) { setErr("Paste a video URL first"); return }
    if (!canAfford)  { setErr(`Need ${cost} tokens, you have ${user.tokens}`); return }
    setBusy(true); setErr("")
    try {
      const r = await apiFetch(`/jobs`, { method:"POST", body:JSON.stringify({
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
      <p style={{ color:C.dim, marginBottom:24 }}>Paste a URL Â· configure Â· get viral clips</p>

      {err && <div style={{ background:"#FF555520", border:`1px solid ${C.red}`,
                            borderRadius:8, padding:"10px 14px", color:C.red,
                            fontSize:13, marginBottom:16 }}>{err}</div>}

      {/* URL */}
      <div style={{ ...css.card, marginBottom:16 }}>
        <div style={css.sec}>Video URL</div>
        <input style={css.input}
               placeholder="https://youtube.com/watch?v=â¦  or any video URL"
               value={url} onChange={e=>setUrl(e.target.value)} />
        <div style={{ color:C.dim, fontSize:11, marginTop:6 }}>
          YouTube Â· TikTok Â· Vimeo Â· Twitter Â· Instagram Â· 1000+ sites
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
                hint="Claude finds viral moments and scores each 0â100"
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
        <Toggle label="Smart Reframe â follow speaker" colour={C.gold}
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
            â Admin Access
          </div>
          <div style={{ color:C.dim, fontSize:13 }}>
            No tokens will be deducted Â· No clip limits Â· No restrictions
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
          {busy ? "Starting jobâ¦" : `â¡ Make ${safeCount} Shorts (${cost} tokens)`}
        </button>
      </div>
    </div>
  )
}


// ââ MANAGE ACCESS (main admin only) ââââââââââââââââââââââââââââââ

function ManageAccess({ token, onNav }) {
  const [users,   setUsers]   = useState([])
  const [loading, setLoading] = useState(true)
  const [err,     setErr]     = useState("")

  const load = useCallback(() => {
    setLoading(true)
    apiFetch("/admin/users", {}, token)
      .then(u => { setUsers(u); setLoading(false) })
      .catch(e => { setErr(e.message); setLoading(false) })
  }, [token])

  useEffect(() => { load() }, [load])

  const toggle = async (u) => {
    try {
      await apiFetch(`/admin/users/${u.id}/social-access`,
        { method:"POST", body: JSON.stringify({ enabled: !u.can_connect_socials }) }, token)
      load()
    } catch(e) { alert(e.message) }
  }

  return (
    <div style={{ maxWidth:760, margin:"0 auto", padding:"32px 24px" }}>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:16 }}>
        <div style={{ fontSize:22, fontWeight:700, color:C.gold, fontFamily:"'Georgia', serif" }}>
          Manage Social-Connect Access
        </div>
        <button style={css.btn(C.field, C.dim)} onClick={() => onNav("dashboard")}>â Dashboard</button>
      </div>
      <div style={{ color:C.dim, fontSize:13, marginBottom:20 }}>
        Toggle which accounts can connect their own social media accounts (YouTube, TikTok, Instagram, Facebook).
      </div>
      {err && <div style={{ color:C.red, marginBottom:12 }}>{err}</div>}
      {loading ? (
        <div style={{ color:C.dim }}>Loadingâ¦</div>
      ) : (
        <div style={css.card}>
          {users.map(u => (
            <div key={u.id} style={{ display:"flex", alignItems:"center", justifyContent:"space-between",
                                     padding:"10px 0", borderBottom:`1px solid ${C.border}` }}>
              <div>
                <div style={{ color:C.text, fontSize:14 }}>{u.email}</div>
                <div style={{ color:C.dim, fontSize:12 }}>
                  {u.plan} {u.is_admin ? "Â· admin" : ""}
                </div>
              </div>
              <button style={css.btn(u.can_connect_socials ? C.emerald : C.field,
                                      u.can_connect_socials ? C.dark : C.dim)}
                      onClick={() => toggle(u)}>
                {u.can_connect_socials ? "â Access Granted" : "Grant Access"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


// -- FOOTER --------------------------------------------------------
function Footer({ onNav }) {
  const link = { color:C.dim, cursor:"pointer", textDecoration:"underline" }
  return (
    <div style={{ borderTop:`1px solid ${C.border}`, marginTop:60, padding:"24px 16px",
                  textAlign:"center", fontSize:12.5, color:C.dim, lineHeight:2 }}>
      <span style={link} onClick={()=>onNav("privacy")}>Privacy Policy</span>
      {"  ·  "}
      <span style={link} onClick={()=>onNav("terms")}>Terms of Service</span>
      {"  ·  "}
      <a href="mailto:squeekydoorphotos@gmail.com" style={link}>squeekydoorphotos@gmail.com</a>
      <div>© 2026 Squeeky Door Productions · SDP Shorts</div>
    </div>
  )
}

// -- POLICY PAGES --------------------------------------------------
function PolicyShell({ title, children }) {
  return (
    <div style={{ maxWidth:760, margin:"40px auto 0", padding:"0 24px" }}>
      <h1 style={{ color:C.gold, fontFamily:"'Georgia', serif", fontWeight:400 }}>{title}</h1>
      <div style={{ color:C.dim, fontSize:13, marginBottom:24 }}>Last updated: June 11, 2026</div>
      <div style={{ ...css.card, lineHeight:1.7, fontSize:14.5 }}>{children}</div>
    </div>
  )
}
function PolicyH({ children }) {
  return <h3 style={{ color:C.gold, marginTop:26, marginBottom:8,
                      fontFamily:"'Georgia', serif", fontWeight:400 }}>{children}</h3>
}

function PrivacyPolicy() {
  const a = { color:C.emerald }
  return (
    <PolicyShell title="Privacy Policy">
      <p>SDP Shorts is run by Squeeky Door Productions ("we", "us") in Spokane, Washington.
      This policy explains what information we collect, why, and what we do with it — in plain
      English. The short version: we collect only what the app needs to work, and we never sell
      your data.</p>

      <PolicyH>What we collect</PolicyH>
      <p><b>Account info.</b> Your email address and a securely hashed version of your password
      (we cannot see your actual password). We also store your plan, token balance, and account
      creation date.</p>
      <p><b>Payment info.</b> Payments are processed by Stripe and PayPal. Your card or bank
      details go directly to them and never touch our servers. We store only a customer
      reference ID and your purchase history so we can credit your account.</p>
      <p><b>Your content.</b> The video links you submit, the clips we generate for you, and
      processing logs needed to run and troubleshoot jobs.</p>
      <p><b>YouTube connection (optional).</b> If you choose to connect your YouTube account,
      we store an access token plus your channel name and ID, used only to upload clips you
      explicitly choose to publish and to show your connection status.</p>
      <p><b>Cookies.</b> We use one essential cookie to keep you logged in. No advertising or
      tracking cookies.</p>

      <PolicyH>What we never do</PolicyH>
      <p>We do not sell, rent, or trade your personal information. We do not run third-party
      ad trackers. We do not read your videos for anything other than generating your clips.</p>

      <PolicyH>How we use your information</PolicyH>
      <p>To provide the service (process videos, generate clips, manage your token balance),
      to process payments, to send account emails (verification, password resets), and to
      respond when you contact support.</p>

      <PolicyH>Who we share it with</PolicyH>
      <p>Only the service providers required to run the app: Stripe and PayPal (payments),
      our hosting providers (the app runs on Railway and Netlify), and Google/YouTube if you
      connect your channel. Each receives only what it needs to do its job. We may also
      disclose information if the law requires it.</p>

      <PolicyH>YouTube API Services</PolicyH>
      <p>SDP Shorts uses YouTube API Services. By connecting your YouTube account you also
      agree to the <a style={a} href="https://www.youtube.com/t/terms" target="_blank"
      rel="noreferrer">YouTube Terms of Service</a>, and Google's handling of your data is
      described in the <a style={a} href="https://policies.google.com/privacy" target="_blank"
      rel="noreferrer">Google Privacy Policy</a>. We access only the ability to upload videos
      you choose and basic channel info. You can disconnect at any time from your dashboard,
      or revoke our access in your{" "}
      <a style={a} href="https://security.google.com/settings/security/permissions"
      target="_blank" rel="noreferrer">Google security settings</a>. When you disconnect,
      we delete the stored tokens.</p>

      <PolicyH>How long we keep things</PolicyH>
      <p>Account data is kept while your account is active. Generated clips are stored so you
      can download them and may be removed after a reasonable period. To delete your account
      and data, email us at <a style={a}
      href="mailto:squeekydoorphotos@gmail.com">squeekydoorphotos@gmail.com</a> and we will
      delete it within 30 days, except records we must keep for legal or accounting reasons
      (like payment history).</p>

      <PolicyH>Security</PolicyH>
      <p>All traffic is encrypted with HTTPS, passwords are hashed, and login sessions use
      secure httpOnly cookies. No system is 100% secure, but we take reasonable measures to
      protect your data.</p>

      <PolicyH>Children</PolicyH>
      <p>SDP Shorts is not intended for children under 13, and we do not knowingly collect
      their information.</p>

      <PolicyH>Changes & contact</PolicyH>
      <p>If we change this policy, we will update this page and the date above. Questions?
      Email <a style={a}
      href="mailto:squeekydoorphotos@gmail.com">squeekydoorphotos@gmail.com</a>.</p>
    </PolicyShell>
  )
}

function TermsOfService() {
  const a = { color:C.emerald }
  return (
    <PolicyShell title="Terms of Service">
      <p>These terms are an agreement between you and Squeeky Door Productions ("we", "us"),
      Spokane, Washington, covering your use of SDP Shorts. By creating an account or using
      the service, you agree to them.</p>

      <PolicyH>What SDP Shorts is</PolicyH>
      <p>SDP Shorts is an AI-powered tool that turns videos into short clips, including
      automatic transcription, captions, titles, and clip selection.</p>

      <PolicyH>AI-generated content disclaimer</PolicyH>
      <p><b>Clips, transcriptions, captions, titles, and scores are generated by artificial
      intelligence and may contain errors, inaccuracies, or awkward results.</b> Always review
      AI-generated content before publishing it anywhere. We are not responsible for the
      accuracy of AI output or for the consequences of publishing it unreviewed.</p>

      <PolicyH>Your account</PolicyH>
      <p>You must be at least 13 to use SDP Shorts and at least 18 (or have a parent's
      permission) to make purchases. Keep your password private — you are responsible for
      activity on your account.</p>

      <PolicyH>Payments, tokens & refunds</PolicyH>
      <p>The service uses tokens, available through plans and top-ups. <b>All sales are
      final.</b> Purchases, including unused tokens and subscription fees, are non-refundable
      except where the law requires otherwise. We may change pricing, and will give notice of
      changes that affect an active subscription. Tokens have no cash value and cannot be
      transferred.</p>

      <PolicyH>Your content</PolicyH>
      <p>You must own the videos you submit or have permission to use them. You keep ownership
      of your videos and the clips we generate from them. You give us only the limited
      permission needed to process and store them so the service can work. Do not submit
      content that is illegal or that infringes someone else's rights — you are solely
      responsible for the content you process and publish.</p>

      <PolicyH>Publishing to YouTube</PolicyH>
      <p>If you connect a YouTube account and publish clips, you are responsible for
      complying with the <a style={a} href="https://www.youtube.com/t/terms" target="_blank"
      rel="noreferrer">YouTube Terms of Service</a> and any other platform rules.</p>

      <PolicyH>Acceptable use</PolicyH>
      <p>Don't abuse the service: no attempts to hack, overload, or reverse-engineer it, no
      reselling access, and no using it for anything unlawful. We may suspend or close
      accounts that violate these terms; tokens on a closed account in violation are
      forfeited.</p>

      <PolicyH>Service availability</PolicyH>
      <p>We work hard to keep SDP Shorts running, but it is provided "as is" without
      warranties of any kind, and we do not guarantee uninterrupted service. We may modify
      or discontinue features.</p>

      <PolicyH>Limitation of liability</PolicyH>
      <p>To the maximum extent allowed by law, our total liability to you for any claim is
      limited to the amount you paid us in the 12 months before the claim, and we are not
      liable for indirect, incidental, or consequential damages (such as lost profits or
      lost content).</p>

      <PolicyH>Governing law & changes</PolicyH>
      <p>These terms are governed by the laws of the State of Washington, USA. If we make
      material changes, we will update this page and the date above; continuing to use the
      service means you accept the updated terms.</p>

      <PolicyH>Contact</PolicyH>
      <p>Questions about these terms? Email <a style={a}
      href="mailto:squeekydoorphotos@gmail.com">squeekydoorphotos@gmail.com</a>.</p>
    </PolicyShell>
  )
}
