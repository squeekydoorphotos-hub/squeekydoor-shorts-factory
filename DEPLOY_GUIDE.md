# SDP Shorts — Deploy Guide
## Plain English, step by step

---

## 🗂️ YOUR FOLDER STRUCTURE

You have two folders to deploy:

```
sdp-shorts/
├── backend/     ← Goes on Railway (runs the Python server)
│   ├── main.py
│   ├── processor.py
│   ├── requirements.txt
│   ├── Procfile
│   ├── nixpacks.toml
│   └── .env.example
│
└── frontend/    ← Goes on Netlify (the website people see)
    ├── src/
    │   ├── App.jsx
    │   └── main.jsx
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── netlify.toml
```

---

## STEP 1 — Put your code on GitHub (you need this for Railway)

1. Go to **github.com** and sign up if you don't have an account (it's free)
2. Click the **+** icon → **New repository**
3. Name it `sdp-shorts-backend` → click **Create repository**
4. Upload all the files from your **`backend/`** folder into this repo
   - Click **"uploading an existing file"** on the repo page
   - Drag and drop everything in the backend folder
   - Click **Commit changes**

Do the same for the frontend:
- Create another repo called `sdp-shorts-frontend`
- Upload everything from the **`frontend/`** folder

---

## STEP 2 — Deploy the backend on Railway

1. Go to **railway.app** → click **Login with GitHub**
2. Click **New Project** → **Deploy from GitHub repo**
3. Pick your `sdp-shorts-backend` repo
4. Railway will detect it's a Python app and start building

### Set your environment variables on Railway:
- In your Railway project, click **Variables**
- Add each variable from `.env.example` with your real values:

| Variable | What to put |
|---|---|
| `SECRET_KEY` | Any random text (e.g. `SuperSecret123ABCxyz!!abc123`) |
| `CLAUDE_API_KEY` | Your key from console.anthropic.com |
| `FRONTEND_URL` | `https://shorts.squeekydoorproductions.com` |
| `STRIPE_SECRET_KEY` | Skip for now (payments won't work yet) |
| `PAYPAL_CLIENT_ID` | Skip for now |

5. After setting variables, Railway will redeploy automatically
6. Click on your deployment → **Settings** → copy the **Domain** URL
   - It'll look like: `sdp-shorts-backend-production.up.railway.app`
   - **Save this URL — you need it for Step 3**

---

## STEP 3 — Deploy the frontend on Netlify

1. Go to **netlify.com** (you already have an account!)
2. Click **Add new site** → **Import an existing project**
3. Connect GitHub → pick your `sdp-shorts-frontend` repo
4. Build settings should auto-fill (Netlify reads your `netlify.toml`):
   - Build command: `npm run build`
   - Publish directory: `dist`
5. Before you click deploy — click **Environment variables** and add:
   - Key: `VITE_API_URL`
   - Value: `https://YOUR-RAILWAY-URL.up.railway.app` (the URL from Step 2)
6. Click **Deploy site**
7. Netlify will give you a URL like `random-name-123.netlify.app`

---

## STEP 4 — Connect your domain (shorts.squeekydoorproductions.com)

### In Netlify:
1. Go to your site → **Domain management** → **Add custom domain**
2. Type: `shorts.squeekydoorproductions.com`
3. Netlify will show you DNS records to add (a CNAME record)
4. Copy the CNAME value (looks like `fancy-name.netlify.app`)

### In Squarespace:
1. Go to your Squarespace site → **Settings** → **Domains**
2. Click on `squeekydoorproductions.com` → **DNS Settings**
3. Scroll down and click **Add Record**
4. Choose **CNAME**
   - Host: `shorts`
   - Points to: (paste what Netlify gave you)
5. Save it — DNS takes up to 24 hours to spread, but usually under 1 hour

---

## STEP 5 — Add a link on your Squarespace site

1. In Squarespace, edit your page
2. Add a **Button** block
3. Set the link to: `https://shorts.squeekydoorproductions.com`
4. Label it something like "Try SDP Shorts →"
5. You can keep the page unpublished until you're ready to go live

---

## ✅ DONE! Your app should be live at:
**https://shorts.squeekydoorproductions.com**

---

## ❓ Troubleshooting

**Backend won't start on Railway?**
- Check the logs in Railway → click on your deployment → **View logs**
- Most common issue: a missing environment variable

**Frontend shows "Network Error" when logging in?**
- The `VITE_API_URL` variable is wrong — double-check it matches your Railway URL exactly (no trailing slash)

**Subdomain not working?**
- Wait an hour and try again — DNS is slow sometimes
- Make sure the CNAME record in Squarespace says `shorts` (not `shorts.squeekydoorproductions.com`)
