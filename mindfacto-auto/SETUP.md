# MindFacto ऑटो Shorts: फ़ोन से सेटअप

## 1. GitHub रेपो
1. github.com पर अकाउंट बनाएँ, फिर New repository बनाएँ। नाम: `mindfacto-auto`। **Public** चुनें (फ़्री मिनट के लिए)।
2. Add file → Create new file से ये 4 फ़ाइलें बनाएँ। नाम में `/` टाइप करने पर फ़ोल्डर अपने आप बनता है। हर फ़ाइल में दिया गया टेक्स्ट कॉपी करके चिपकाएँ, फिर Commit करें।
   - `main.py`
   - `requirements.txt`
   - `history.json`  (अंदर सिर्फ़ `[]`)
   - `.github/workflows/daily.yml`

## 2. Gemini key
aistudio.google.com/apikey → Create API key → कॉपी करें।

## 3. Pexels key
pexels.com/api → फ़्री अकाउंट → key कॉपी करें।

## 4. YouTube की अनुमति (सबसे लंबा हिस्सा)
1. console.cloud.google.com → New Project बनाएँ।
2. APIs & Services → Library → "YouTube Data API v3" → Enable।
3. APIs & Services → OAuth consent screen → External चुनें, ऐप का नाम भरें, Test users में अपनी Gmail जोड़ें।
   **ज़रूरी:** इसके बाद Publish app दबाकर "In production" कर दें। Testing में रहने पर टोकन 7 दिन में बंद हो जाता है।
4. Credentials → Create credentials → OAuth client ID → Web application।
   Authorized redirect URI में डालें: `https://developers.google.com/oauthplayground`
   → **Client ID** और **Client secret** कॉपी करें।
5. developers.google.com/oauthplayground खोलें → ऊपर दाएँ गियर → "Use your own OAuth credentials" टिक करें → Client ID और secret डालें।
6. Step 1 में नीचे के बॉक्स में `https://www.googleapis.com/auth/youtube.upload` लिखकर Authorize APIs दबाएँ। **उसी Gmail से लॉगिन करें जिसमें MindFacto चैनल है।**
   ("unverified app" की चेतावनी आए तो Advanced → Go to app।)
7. Step 2 में "Exchange authorization code for tokens" दबाएँ → **Refresh token** कॉपी करें।

## 5. Secrets डालना
रेपो → Settings → Secrets and variables → Actions → New repository secret। ये 5 नाम बिल्कुल ऐसे ही रखें:
`GEMINI_API_KEY`, `PEXELS_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`

## 6. पहली बार चलाना
Actions टैब → daily-short → Run workflow → dry_run में `1` लिखें → Run।
लॉग में "Video ready" दिखे तो वीडियो बन गया। फिर `0` से चलाएँ तो अपलोड भी होगा।
उसके बाद रोज़ सुबह 9:00 बजे (IST) अपने आप चलेगा।

## ध्यान रखें
- नए API प्रोजेक्ट की अपलोड की गई वीडियो शुरू में **Private** रह सकती हैं। YouTube Studio में जाकर Public कर दें, या audit का फ़ॉर्म भरें।
- keys कभी किसी को चैट में या कोड में न दें।
- बदलाव: `daily.yml` में TOPIC (विषय), VOICE (आवाज़: `hi-IN-SwaraNeural` महिला की है), और cron (समय) बदल सकते हैं।
