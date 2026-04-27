// server.js — Local Playwright server
// Run: node server.js
// Then open login.html in your browser

const http = require("http");
const { chromium } = require("playwright");

const PORT = 3000;

const server = http.createServer(async (req, res) => {
  // Allow login.html to talk to this server
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === "POST" && req.url === "/login") {
    let body = "";
    req.on("data", chunk => (body += chunk));
    req.on("end", async () => {
      try {
        const { username, password, targetUrl, usernameSelector, passwordSelector, submitSelector } = JSON.parse(body);

        if (!username || !password || !targetUrl) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ success: false, error: "Missing fields" }));
          return;
        }

        console.log(`Logging in to: ${targetUrl}`);

        const browser = await chromium.launch({ headless: false }); // Set true to run silently
        const page = await browser.newPage();

        await page.goto(targetUrl);
        await page.waitForSelector(usernameSelector);

        await page.fill(usernameSelector, username);
        await page.fill(passwordSelector, password);
        await page.click(submitSelector);
        await page.waitForLoadState("networkidle");

        console.log(`Redirected to: ${page.url()}`);

        // Credentials are used and cleared — not stored anywhere
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: true, redirectedTo: page.url() }));

        // Don't close browser so user can see result
        // await browser.close();

      } catch (err) {
        console.error("Playwright error:", err.message);
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: false, error: err.message }));
      }
    });

  } else {
    res.writeHead(404);
    res.end("Not found");
  }
});

server.listen(PORT, () => {
  console.log(`✓ Playwright server running at http://localhost:${PORT}`);
  console.log(`  Open login.html in your browser to use it.`);
});
