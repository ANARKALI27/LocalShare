# LocalShare — आसान Manual (Hindi)

ये file बहुत simple भाषा में बताती है कि LocalShare install कैसे करें,
use कैसे करें, और Internet पर share (Cloudflare) कैसे करें।

**ज़रूरी बात:** पहले ये app ngrok use करता था, लेकिन अब सिर्फ
**Cloudflare** use होता है — इसलिए किसी account या sign up की ज़रूरत
नहीं है। नीचे सिर्फ Cloudflare वाला तरीका बताया गया है।

---

## 1. Windows पर Install कैसे करें

1. `LocalShareSetup.exe` file डाउनलोड करें (या project से खुद बनाएं —
   नीचे "खुद Build करना" section देखें)।
2. उस file पर **double-click** करें।
3. अगर Windows कोई warning दिखाए ("Windows protected your PC"), तो
   **"More info"** पर click करें, फिर **"Run anyway"** दबाएं। ये
   warning इसलिए आती है क्योंकि ये app किसी बड़ी company से signed
   नहीं है — नुकसान वाली बात नहीं है।
4. Setup के instructions follow करें — बस **Next, Next, Install**
   दबाते जाएं।
5. Install होने के बाद, LocalShare अपने आप खुल जाएगा (या Start Menu
   से खोलें)।

**Uninstall करना हो तो:** Windows Settings → Apps → LocalShare ढूंढें
→ Uninstall दबाएं।

---

## 2. Linux (.deb) पर Install कैसे करें

अगर आपके पास `localshare_*.deb` file है (Ubuntu, Debian, Linux Mint
जैसे systems के लिए):

**तरीका 1 — Double-click से:**
1. `.deb` file पर double-click करें।
2. जो Software installer खुले, उसमें **"Install"** दबाएं।
3. अपना password डालें (अगर मांगे)।

**तरीका 2 — Terminal से (ज्यादा भरोसेमंद):**
```bash
sudo dpkg -i localshare_*.deb
sudo apt-get install -f     # अगर कोई dependency missing हो तो ये उसे ठीक कर देगा
```

Install होने के बाद, LocalShare अपने Applications menu में मिल
जाएगा।

**Uninstall करना हो तो:**
```bash
sudo apt-get remove localshare
```

---

## 3. LocalShare Use कैसे करें (Basic)

1. **LocalShare खोलें।**
2. **Files या Folder को खींचकर (drag & drop) window में डालें** — या
   "Add Files…" / "Add Folder…" बटन दबाएं।
3. **Sharing Mode चुनें:**
   - **Local Network Only** (default) — सिर्फ उन लोगों के लिए जो
     आपके साथ **same Wi-Fi** पर हैं। कोई PIN ज़रूरी नहीं (चाहें तो
     लगा सकते हैं)।
   - **Global** — किसी भी जगह से किसी को भी share करने के लिए, चाहे
     वो आपके Wi-Fi पर न हो। इसमें PIN automatically लग जाता है (बंद
     नहीं कर सकते, security के लिए)।
4. **"Start Sharing"** दबाएं। एक address (link) और QR code दिख जाएगा।
5. वो address (या QR code) जिसे share करना है, उसे भेज दें।
6. सामने वाला व्यक्ति उस link को किसी भी browser में खोल सकता है —
   files देख सकता है, download कर सकता है, और (अगर folder के अंदर है)
   अपनी files upload भी कर सकता है।
7. काम खत्म होने पर **"Stop Sharing"** दबा दें।

---

## 4. Internet पर Share करना (Cloudflare, "Global" Mode)

**सबसे अच्छी बात: कुछ भी install या setup करने की ज़रूरत नहीं है।**
कोई account नहीं, कोई sign up नहीं, कोई password नहीं।

### कैसे use करें:

1. LocalShare में **"Global"** mode चुनें (Local Network Only की
   जगह)।
2. **"Start Sharing"** दबाएं।
3. **पहली बार** use करते समय, LocalShare अपने आप `cloudflared` नाम की
   एक छोटी सी file (लगभग 40MB) download कर लेगा — इसमें कुछ seconds
   लग सकते हैं। ये सिर्फ **एक बार** होता है; अगली बार से turant चालू
   हो जाएगा।
4. कुछ ही सेकंड में एक Internet address मिल जाएगा (जैसे
   `https://कुछ-शब्द.trycloudflare.com`) — यही link सामने वाले को
   भेजनी है। ये link दुनिया में कहीं से भी खुल सकती है।
5. PIN भी screen पर दिखेगा (Global mode में PIN ज़रूरी है) — वो भी
   सामने वाले को बता दें, या सिर्फ QR code भेज दें (उसमें PIN अपने आप
   शामिल रहता है)।

### अगर automatic download fail हो जाए (rare case):

अगर आपके network/firewall की वजह से automatic download काम न करे, तो
`cloudflared` को manually भी install कर सकते हैं:

**Windows (Command Prompt/PowerShell में):**
```
winget install --id Cloudflare.cloudflared
```

**Linux पर (आसान तरीका — किसी भी distro पर चलता है):**

सीधे binary file download करें (कोई package manager setup नहीं
चाहिए):
👉 https://github.com/cloudflare/cloudflared/releases/latest

(`cloudflared-linux-amd64` वाली file चुनें, फिर उसे executable बनाएं:
`chmod +x cloudflared-linux-amd64`)

**या** अगर Ubuntu/Debian पर apt से install करना है, तो पहले
Cloudflare की अपनी repository add करनी होगी — पूरी जानकारी यहाँ है:
👉 https://pkg.cloudflare.com/index.html
(सिर्फ `apt-get install cloudflared` से काम नहीं चलेगा, पहले repo
add करना ज़रूरी है)

Install करने के बाद LocalShare को पूरी तरह बंद करके दोबारा खोलें,
फिर "Global" mode try करें।

### याद रखने वाली बातें (Cloudflare के बारे में):

- हर बार जब आप "Start Sharing" दबाते हैं, एक **नया** link बनता है —
  पुराना link "Stop Sharing" दबाते ही बंद हो जाता है।
- ये link **temporary/testing** के लिए है, बहुत ज़्यादा traffic या
  हमेशा चालू रखने के लिए नहीं बना है — दोस्तों के साथ files share
  करने के लिए बिलकुल सही है।

---

## 5. खुद Build करना (सिर्फ अगर source code से बना रहे हैं)

**Windows:**
```
build_installer.bat
```
इससे `Output\LocalShareSetup.exe` बन जाएगा।

**Linux (.deb):**
```bash
./build_deb.sh
```
इससे एक `.deb` file बन जाएगी जो ऊपर बताए तरीके से install हो सकती
है।

---

अगर कोई दिक्कत आए, तो `README.md` और `GUIDE.md` में और detail मिल
जाएगी (English में)।
