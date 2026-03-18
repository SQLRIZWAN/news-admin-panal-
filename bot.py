"""
KWT News — AI Auto News Bot
GitHub Actions mein har ghante automatically chalega.
"""

import os
import json
import time
import hashlib
import requests
import xml.etree.ElementTree as ET
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# ── Config ────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDunpdQAAEIjQXr40arN630WUJi-rK2S3Q")
FIREBASE_CONFIG = os.environ.get("FIREBASE_CONFIG", "")

NEWS_FEEDS = [
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",    "source": "BBC News",   "domain": "bbc.co.uk"},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml",       "source": "Al Jazeera", "domain": "aljazeera.com"},
    {"url": "https://feeds.skynews.com/feeds/rss/world.xml",   "source": "Sky News",   "domain": "skynews.com"},
    {"url": "https://rss.cnn.com/rss/edition_world.rss",       "source": "CNN World",  "domain": "cnn.com"},
]

MAX_PER_RUN = 5  # har run mein max 5 articles

# ── Firebase Init ─────────────────────────────────────────────
def init_firebase():
    if FIREBASE_CONFIG:
        cred_dict = json.loads(FIREBASE_CONFIG)
        cred = credentials.Certificate(cred_dict)
    else:
        # Local testing: serviceAccountKey.json use karo
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    return firestore.client()

# ── RSS Fetch ─────────────────────────────────────────────────
def fetch_feed(feed):
    items = []
    try:
        r = requests.get(feed["url"], timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        
        # Standard RSS
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            link  = item.findtext("link", "").strip()
            if title and len(title) > 10:
                items.append({
                    "title":   title,
                    "content": desc,
                    "link":    link,
                    "feedSource": feed,
                })
        
        # Atom feed fallback
        if not items:
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                summ  = (entry.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()
                link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                link = link_el.get("href","") if link_el is not None else ""
                if title:
                    items.append({"title": title, "content": summ, "link": link, "feedSource": feed})
        
        print(f"  ✅ {feed['source']}: {len(items)} articles")
    except Exception as e:
        print(f"  ❌ {feed['source']}: {e}")
    return items

# ── Duplicate Check ───────────────────────────────────────────
def get_existing_titles(db):
    titles = set()
    docs = db.collection("news").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(200).stream()
    for doc in docs:
        t = (doc.to_dict().get("title") or "").lower().strip()
        if t:
            titles.add(t)
    return titles

# ── Gemini Rewrite ────────────────────────────────────────────
def rewrite_with_gemini(item):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    raw = (item["content"] or item["title"] or "")[:600]
    # Remove HTML tags
    import re
    raw = re.sub(r"<[^>]+>", "", raw).strip()
    
    prompt = f"""You are a professional news editor for KWT News.
Rewrite this article following ALL rules exactly.

TITLE: {item['title']}
CONTENT: {raw}
SOURCE: {item['feedSource']['source']} ({item['feedSource']['domain']})

STRICT RULES:
- New catchy title (max 10 words)
- Summary: exactly 2 sentences, max 40 words total
- Article body: EXACTLY 120 words, simple English, last sentence must say "Source: {item['feedSource']['domain']}"
- Category: "kuwait" if about Kuwait/Gulf/Arab/Middle East, else "world"
- Keyword: ONE English word for image search (e.g. politics, economy, war, sports, technology, climate)

Reply ONLY with valid JSON. No markdown, no backticks, no extra text:
{{"title":"...","summary":"...","content":"...","category":"world","keyword":"news"}}"""
    
    response = model.generate_content(prompt)
    text = response.text.strip()
    
    # Parse JSON safely
    import re
    text = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(text)
    except:
        match = re.search(r"\{[\s\S]*?\}", text)
        if match:
            return json.loads(match.group(0))
        raise ValueError("Gemini returned invalid JSON")

# ── Main Bot ──────────────────────────────────────────────────
def main():
    print("🤖 KWT News AI Bot Starting...")
    print("=" * 50)
    
    # Firebase connect
    db = init_firebase()
    print("✅ Firebase connected")
    
    # Fetch all feeds
    print("\n📡 Fetching RSS feeds...")
    all_items = []
    for feed in NEWS_FEEDS:
        all_items.extend(fetch_feed(feed))
    
    print(f"\n📰 Total fetched: {len(all_items)} articles")
    
    # Duplicate check
    print("🔍 Checking duplicates in Firebase...")
    existing = get_existing_titles(db)
    
    new_items = []
    for item in all_items:
        t = item["title"].lower().strip()
        if len(t) > 10 and t not in existing:
            new_items.append(item)
    
    print(f"✨ New articles: {len(new_items)} | Skipped: {len(all_items) - len(new_items)} duplicates")
    
    if not new_items:
        print("ℹ️  No new articles. Exiting.")
        return
    
    # Process up to MAX_PER_RUN
    to_process = new_items[:MAX_PER_RUN]
    saved = 0
    
    for i, item in enumerate(to_process):
        print(f"\n[{i+1}/{len(to_process)}] 🤖 Rewriting: {item['title'][:60]}...")
        
        try:
            parsed = rewrite_with_gemini(item)
            
            if not parsed.get("title") or not parsed.get("content"):
                print("  ⚠️  Missing fields, skipping")
                continue
            
            # Image from loremflickr (free, no API key needed)
            kw = (parsed.get("keyword") or "news").lower().replace(" ", "-")
            seed = int(time.time()) + i
            image_url = f"https://loremflickr.com/800/450/{kw}?lock={seed}"
            
            # Save to Firestore
            doc = {
                "title":        parsed["title"].strip(),
                "summary":      parsed["summary"].strip(),
                "content":      parsed["content"].strip(),
                "imageUrl":     image_url,
                "thumbnail":    image_url,
                "category":     parsed.get("category", "world"),
                "source":       item["feedSource"]["source"],
                "sourceDomain": item["feedSource"]["domain"],
                "originalUrl":  item.get("link", ""),
                "originalTitle": item["title"],
                "status":       "draft",
                "aiGenerated":  True,
                "isBreaking":   False,
                "hidden":       True,
                "readTime":     "2 min read",
                "mediaType":    "image",
                "views":        0,
                "likes":        0,
                "commentCount": 0,
                "timestamp":    firestore.SERVER_TIMESTAMP,
                "aiCreatedAt":  firestore.SERVER_TIMESTAMP,
            }
            
            db.collection("news").add(doc)
            saved += 1
            print(f"  ✅ Saved: {parsed['title'][:60]}")
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
        
        # Rate limit (Gemini free tier)
        if i < len(to_process) - 1:
            time.sleep(2)
    
    print(f"\n{'='*50}")
    print(f"🎉 Done! Saved {saved}/{len(to_process)} drafts → Check Admin Panel → News → 🤖 AI Drafts")


if __name__ == "__main__":
    main()
