const { initializeApp } = require("firebase/app");
const { getFirestore, collection, addDoc, serverTimestamp } = require("firebase/firestore");
const { GoogleGenerativeAI } = require("@google/generative-ai");

// ✅ Firebase & Gemini Setup
const firebaseConfig = JSON.parse(process.env.FIREBASE_CONFIG);
const app = initializeApp(firebaseConfig);
const db = getFirestore(app);
const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });

// ✅ Sari Categories
const CATEGORIES = [
  { id: "pakistan", label: "Pakistan News" },
  { id: "world", label: "World News" },
  { id: "politics", label: "Politics" },
  { id: "technology", label: "Technology" },
  { id: "sports", label: "Sports" },
  { id: "cricket", label: "Cricket" },
  { id: "business", label: "Business & Economy" },
  { id: "entertainment", label: "Entertainment" },
  { id: "health", label: "Health" },
  { id: "science", label: "Science" },
  { id: "education", label: "Education" },
  { id: "crime", label: "Crime & Law" },
];

// ✅ Ek category ke liye news generate karo
async function generateNewsForCategory(category) {
  const prompt = `
You are a professional news journalist. Generate 2 latest realistic news articles for the category: "${category.label}".

Return ONLY a valid JSON array with this exact format:
[
  {
    "title": "News headline here",
    "summary": "Short 2-3 line summary of the news",
    "content": "Full detailed news article of at least 5-6 paragraphs",
    "source": "Source name e.g. Reuters, BBC, ARY News",
    "imageKeyword": "one keyword for image search"
  }
]

Rules:
- News must be realistic and current (2025-2026)
- Title must be catchy and professional
- Content must be detailed and informative
- No markdown, no extra text, ONLY the JSON array
`;

  try {
    const result = await model.generateContent(prompt);
    const text = result.response.text();
    
    // JSON extract karo
    const jsonMatch = text.match(/\[[\s\S]*\]/);
    if (!jsonMatch) throw new Error("No JSON found in response");
    
    const articles = JSON.parse(jsonMatch[0]);
    return articles;
  } catch (err) {
    console.error(`❌ Error generating news for ${category.label}:`, err.message);
    return [];
  }
}

// ✅ Firebase mein save karo
async function saveNewsToFirebase(article, category) {
  try {
    const docData = {
      title: article.title,
      summary: article.summary,
      content: article.content,
      category: category.id,
      categoryLabel: category.label,
      source: article.source || "AI Generated",
      imageKeyword: article.imageKeyword || category.id,
      imageUrl: `https://source.unsplash.com/800x450/?${encodeURIComponent(article.imageKeyword || category.id)}`,
      isAIGenerated: true,
      views: 0,
      likes: 0,
      publishedAt: new Date().toISOString(),
      createdAt: serverTimestamp(),
    };

    const docRef = await addDoc(collection(db, "news"), docData);
    console.log(`✅ Saved: [${category.label}] ${article.title} (ID: ${docRef.id})`);
  } catch (err) {
    console.error(`❌ Firebase save error:`, err.message);
  }
}

// ✅ Delay function (rate limit avoid karne ke liye)
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ✅ Main function
async function main() {
  console.log("🚀 News Generation Started...");
  console.log(`📋 Total Categories: ${CATEGORIES.length}`);
  console.log("━".repeat(50));

  let totalSaved = 0;

  for (const category of CATEGORIES) {
    console.log(`\n📰 Generating news for: ${category.label}...`);
    
    const articles = await generateNewsForCategory(category);
    
    for (const article of articles) {
      await saveNewsToFirebase(article, category);
      totalSaved++;
      await delay(500); // Firebase rate limit
    }

    await delay(2000); // Gemini API rate limit
  }

  console.log("\n" + "━".repeat(50));
  console.log(`🎉 Done! Total ${totalSaved} news articles saved to Firebase!`);
  process.exit(0);
}

main().catch((err) => {
  console.error("💥 Fatal Error:", err);
  process.exit(1);
});
