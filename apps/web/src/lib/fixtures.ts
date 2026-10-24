import type { AgentId } from "./agents";

export interface Playbook {
  id: string; name: string; domain: string; tagline: string;
  theme: "aurora" | "sunset";
  accent: string; grad: string;
  sources: string[];
  rubric: { label: string; weight: number }[];
  makers: string[];
  defaultTopic: string;
  emojiBadge: string;
}

export const PLAYBOOKS: Playbook[] = [
  {
    id: "ai-news-gtm", name: "AI News — GTM", domain: "AI News", tagline: "The day's biggest AI story → a full content suite before your coffee cools.",
    theme: "aurora", accent: "#7C6CF0", grad: "linear-gradient(120deg,#38BDF8,#7C6CF0)",
    sources: ["Tavily Search", "Hacker News", "Fetch", "GitHub Trending"],
    rubric: [{ label: "Audience Heat", weight: 40 }, { label: "Consequence", weight: 20 }, { label: "Verification", weight: 20 }, { label: "Novelty", weight: 20 }],
    makers: ["Briefing", "Reel Script", "Carousel", "LinkedIn", "Instagram", "Email"],
    defaultTopic: "today's top AI story", emojiBadge: "🤖",
  },
  {
    id: "travel-news", name: "Travel — GTM", domain: "Travel News", tagline: "Same agents. New continent. Swap the playbook, keep the magic.",
    theme: "sunset", accent: "#F97316", grad: "linear-gradient(120deg,#FB923C,#EC4899)",
    sources: ["Tavily Travel", "Reddit r/travel", "Fetch"],
    rubric: [{ label: "Deal Value", weight: 35 }, { label: "Urgency", weight: 25 }, { label: "Seasonality", weight: 20 }, { label: "Verification", weight: 20 }],
    makers: ["Deal Briefing", "Carousel", "LinkedIn", "Email"],
    defaultTopic: "this week's best flight deals", emojiBadge: "✈️",
  },
];

export interface Slide { kicker: string; title: string; body: string; g1: string; g2: string; }
export interface Artifact {
  id: string; label: string; icon: string; maker: AgentId;
  kind: "text" | "slides";
  pieces: string[];          // text pieces, revealed one by one
  slides?: Slide[];          // carousel slides, revealed one by one
  verdict: string;           // reviewer note for this artifact
}
export interface Candidate { title: string; score: number; heat: number; note: string; }
export interface ToolCall { name: string; detail: string; result: string; }

export type DemoEvent =
  | { t: number; kind: "status"; agent: AgentId; status: "working" | "done" | "waiting"; line?: string }
  | { t: number; kind: "line"; agent: AgentId; line: string }
  | { t: number; kind: "tool"; agent: AgentId; tool: ToolCall }
  | { t: number; kind: "progress"; agent: AgentId; value: number }
  | { t: number; kind: "edge"; edge: string }
  | { t: number; kind: "piece"; artifact: string; index: number }
  | { t: number; kind: "scores"; candidates: Candidate[] }
  | { t: number; kind: "review"; verdict: "PASS" | "REVISE"; notes: string[] }
  | { t: number; kind: "phase"; phase: "running" | "awaiting" | "approved" };

export interface RunFixture {
  artifacts: Artifact[];
  candidates: Candidate[];
  events: DemoEvent[];
  durationMs: number;
  runPageTitle: string;
}

const A = (t: number, agent: AgentId, line: string): DemoEvent => ({ t, kind: "status", agent, status: "working", line });
const D = (t: number, agent: AgentId, line: string): DemoEvent => ({ t, kind: "status", agent, status: "done", line });
const T = (t: number, agent: AgentId, tool: ToolCall): DemoEvent => ({ t, kind: "tool", agent, tool });
const P = (t: number, agent: AgentId, value: number): DemoEvent => ({ t, kind: "progress", agent, value });
const E = (t: number, edge: string): DemoEvent => ({ t, kind: "edge", edge });
const PC = (t: number, artifact: string, index: number): DemoEvent => ({ t, kind: "piece", artifact, index });
const L = (t: number, agent: AgentId, line: string): DemoEvent => ({ t, kind: "line", agent, line });

export const AI_FIXTURE: RunFixture = {
  runPageTitle: "Agents Went Mainstream — AI Daily Brief Suite",
  candidates: [
    { title: "Agents that book, build & browse ship to everyone", score: 91, heat: 38, note: "1,240 HN points, trending on X, 3 independent confirmations" },
    { title: "A benchmark nobody can reproduce", score: 54, heat: 17, note: "Vendor-only numbers — Vera would riot" },
    { title: "Framework releases v2.0 with breaking changes", score: 63, heat: 21, note: "Devs care deeply; everyone else, less so" },
    { title: "Yet another AI logo generator", score: 22, heat: 6, note: "A shrug story. Otto binned it in 0.4s" },
  ],
  artifacts: [
    { id: "briefing", label: "Briefing", icon: "🗞️", maker: "scribe", kind: "text", verdict: "Every claim traced to a source ✓",
      pieces: [
        "**The story:** AI agents crossed from demos to default this week — the major platforms shipped agents that book travel, write and run code, and browse the web end-to-end, with user approval gates built in.",
        "**Why it matters:** This is the GTM moment for agentic AI. The conversation moves from “can it?” to “who's accountable when it does?” — exactly the question our audience of builders is asking.",
        "**Evidence:** 14 sources gathered · 3 independent confirmations · 1,240 Hacker News points · GitHub trending #2 for agent frameworks.",
        "**Angle (ours, not a shrug):** Agents are now products, not prototypes. The winners won't be the most autonomous — they'll be the most *supervisable*.",
      ]},
    { id: "reel_script", label: "Reel Script", icon: "🎬", maker: "scribe", kind: "text", verdict: "Self-contained for a first-time viewer ✓",
      pieces: [
        "**0–3s · HOOK** — “Your AI just booked a flight, wrote the code, and browsed the web — while you watched.”",
        "**3–25s · THE NEWS** — The big platforms shipped agents that don't just chat: they act. Book, build, browse — start to finish, asking permission at the moments that matter.",
        "**25–50s · WHY IT MATTERS** — This is the shift from AI as a tool you drive to AI as a colleague you supervise. The skill of the year isn't prompting. It's reviewing.",
        "**50–60s · THE TAKE** — “Agents went mainstream this week. The question isn't can they act — it's who checks their work. Follow for the 60-second version, every day.”",
      ]},
    { id: "carousel", label: "Carousel", icon: "🎠", maker: "hue", kind: "slides", verdict: "6/6 slides, no clipped bullets ✓", pieces: [],
      slides: [
        { kicker: "AI DEV DIGEST · TOP STORY", title: "Agents went mainstream", body: "Book. Build. Browse. Agents now finish the job — here's what shipped, and why it matters.", g1: "#38BDF8", g2: "#7C6CF0" },
        { kicker: "WHAT SHIPPED", title: "Agents that act, not chat", body: "End-to-end task completion across the major platforms — with approval gates at the moments that count.", g1: "#7C6CF0", g2: "#EC4899" },
        { kicker: "THE PROOF", title: "Builders showed up", body: "1,240 HN points · GitHub trending #2 · three independent confirmations. This isn't a press release.", g1: "#0EA47A", g2: "#38BDF8" },
        { kicker: "WHY IT MATTERS", title: "From tool to colleague", body: "You don't drive an agent. You brief it, watch it work, and review what it ships. New job description.", g1: "#F59E0B", g2: "#F97316" },
        { kicker: "THE CATCH", title: "Autonomy needs a reviewer", body: "The products winning this week all kept a human in the loop for writes, payments, and sends.", g1: "#6366F1", g2: "#38BDF8" },
        { kicker: "THE TAKE", title: "Supervisable beats autonomous", body: "Follow AI Daily Brief — the 60-second version of AI, every day. Full sources in the first comment.", g1: "#E11D48", g2: "#7C6CF0" },
      ]},
    { id: "linkedin_post", label: "LinkedIn Post", icon: "💼", maker: "herald", kind: "text", verdict: "Tone matches brand voice ✓",
      pieces: [
        "Agents went mainstream this week — and almost nobody noticed the real story.\n\nThe launches weren't about smarter chat. They were about AI that finishes jobs: booking, building, browsing, end to end.",
        "Here's the pattern across every launch that landed:\n\n→ Agents act across tools, not inside one chat window\n→ Humans approve the moments that matter — writes, payments, sends\n→ The demo that wins is the one you can *supervise*\n\nThe skill shift is real: prompting was 2024. Reviewing agent work well is 2026.\n\nFull breakdown + sources in the carousel. What would you let an agent do unsupervised?",
      ]},
    { id: "instagram_caption", label: "Instagram Caption", icon: "📸", maker: "herald", kind: "text", verdict: "Hook in first line ✓",
      pieces: [
        "Your AI just booked a flight, shipped code & browsed the web — while you watched 👀🤖",
        "Agents went mainstream this week. Not chatbots. Colleagues you supervise.\n\nFull 60-second breakdown in today's reel 🎬\n\n#AI #AgenticAI #AIagents #TechNews #BuildInPublic",
      ]},
    { id: "email", label: "Email", icon: "✉️", maker: "herald", kind: "text", verdict: "One clear CTA ✓",
      pieces: [
        "**Subject:** Agents went mainstream this week 🤖",
        "Hi there —\n\nQuick one today, because it's a big one: the major platforms shipped AI agents that complete real tasks end to end — booking, building, browsing — with you approving the moments that matter.",
        "We broke down what shipped, the proof it's real, and the one skill that now matters more than prompting.\n\n**→ Read the 2-minute brief**\n\nSee you tomorrow,\nAI Daily Brief",
      ]},
  ],
  events: [], durationMs: 30500,
};

AI_FIXTURE.events = [
  A(0, "supervisor", "New mission! Reading the Playbook… snacks first, then strategy."),
  T(500, "supervisor", { name: "mcp · filesystem", detail: "read_playbook(ai-news-gtm)", result: "Playbook loaded · rubric 40/20/20/20 · 6 artifacts queued" }),
  P(900, "supervisor", 100), D(1300, "supervisor", "Plan set. Pixel — go sniff the internet."),
  E(1400, "supervisor-scout"),
  A(1500, "scout", "Rummaging through the internet's couch cushions…"),
  T(1900, "scout", { name: "mcp · tavily-search", detail: "search('AI agents launch', news, 24h)", result: "14 sources · 6 candidate stories" }),
  P(2600, "scout", 45),
  T(3300, "scout", { name: "mcp · hn-algolia", detail: "top stories, agent keywords", result: "Top candidate at 1,240 points and climbing" }),
  P(4200, "scout", 78),
  T(4700, "scout", { name: "mcp · fetch", detail: "extract 3 primary sources", result: "Full text captured · quotes verified verbatim" }),
  D(5600, "scout", "Found gold: 14 sources, 6 candidates, zero rumours."),
  E(5800, "scout-curator"),
  A(5900, "curator", "Scoring time. Sentiment is not a metric, people."),
  T(6400, "curator", { name: "score_candidates", detail: "Playbook rubric · Audience Heat ×0.40", result: "4 stories scored · 1 runaway winner" }),
  { t: 7300, kind: "scores", candidates: AI_FIXTURE.candidates },
  L(8100, "curator", "91 points. The agents story laps the field — the logo generator never stood a chance."),
  D(8800, "curator", "Winner picked, reasoning on the record. Echo — check we haven't told this one before."),
  E(9000, "curator-archivist"),
  A(9100, "archivist", "Diving into the memory vault… mind the dust, it's from October."),
  T(9600, "archivist", { name: "rag · retrieve", detail: "brand-voice + past-runs (212 briefs)", result: "No duplicates · style pack assembled" }),
  D(10800, "archivist", "Fresh story, voice loaded. Makers — the floor is yours. All three of you. GO."),
  E(11000, "archivist-makers"),
  // ---- PARALLEL FAN-OUT ----
  A(11100, "scribe", "Briefing first, script second, coffee third. Writing!"),
  A(11100, "hue", "Beret on. Making slides people actually swipe."),
  A(11100, "herald", "One story, five outfits. Watch me tailor."),
  T(11600, "scribe", { name: "draft_artifact", detail: "briefing ← evidence pack", result: "Outline locked · 4 sections" }),
  T(11900, "hue", { name: "mcp · carousel", detail: "render_carousel(spec, 1080×1350)", result: "Renderer warmed up · theme sky-violet" }),
  T(12200, "herald", { name: "draft_artifact", detail: "linkedin_post ← style pack", result: "Hook drafted" }),
  PC(12800, "briefing", 0), P(12800, "scribe", 25),
  PC(13600, "carousel", 0), P(13600, "hue", 17),
  PC(14400, "linkedin_post", 0), P(14400, "herald", 30),
  PC(15200, "briefing", 1), P(15200, "scribe", 45),
  PC(15900, "carousel", 1), P(15900, "hue", 33),
  L(16400, "hue", "Slide 2 is *chef's kiss*. Continuing."),
  PC(16600, "reel_script", 0), PC(16900, "instagram_caption", 0), P(16900, "herald", 52),
  PC(17600, "carousel", 2), P(17600, "hue", 50),
  PC(18300, "briefing", 2), P(18300, "scribe", 65),
  PC(19000, "reel_script", 1), PC(19300, "carousel", 3), P(19300, "hue", 67),
  PC(19900, "email", 0), P(19900, "herald", 70),
  PC(20500, "briefing", 3), P(20500, "scribe", 82),
  PC(21100, "carousel", 4), P(21100, "hue", 83),
  PC(21700, "reel_script", 2), PC(22000, "email", 1), P(22000, "herald", 86),
  PC(22600, "instagram_caption", 1),
  PC(23100, "carousel", 5), D(23400, "hue", "Six slides, zero clipped bullets. Michelangelo could never."),
  PC(23800, "reel_script", 3), D(24200, "scribe", "Briefing + script, sealed. The hook lands in 3 seconds — I timed it."),
  PC(24700, "email", 2), D(25100, "herald", "LinkedIn, Instagram, email — same story, all tailored. Vera, be gentle."),
  E(25300, "makers-reviewer"),
  A(25400, "reviewer", "Monocle on. Nobody ships past me unverified."),
  T(25900, "reviewer", { name: "verify_claims", detail: "every claim → source evidence", result: "23 claims · 23 grounded · 0 invented" }),
  P(26800, "reviewer", 70),
  L(27200, "reviewer", "One caption was 4% too spicy. Toned down. You're welcome."),
  { t: 28000, kind: "review", verdict: "PASS", notes: ["23/23 claims grounded in Scout's sources", "No story we've covered before", "Self-contained for a first-time viewer", "Tone matches Playbook voice", "Carousel: 6/6 slides, no clipped bullets"] },
  D(28600, "reviewer", "PASS. Reluctantly delighted. Human — your move."),
  A(29000, "supervisor", "The suite is complete and Vera-approved. Over to you, human. ✨"),
  { t: 29500, kind: "phase", phase: "awaiting" },
];

export const TRAVEL_FIXTURE: RunFixture = {
  runPageTitle: "48-Hour Flight Deals — Travel Brief Suite",
  candidates: [
    { title: "NYC → Lisbon fares drop 41% for late November", score: 93, heat: 36, note: "Verified across 2 fare sources, 48h window" },
    { title: "A new budget route to Reykjavík opens", score: 71, heat: 24, note: "Great deal, narrow dates" },
    { title: "Resort flash sale, 'up to 60% off*'", score: 38, heat: 12, note: "*off a price nobody ever paid. Binned." },
  ],
  artifacts: [
    { id: "briefing", label: "Deal Briefing", icon: "🧳", maker: "scribe", kind: "text", verdict: "Prices re-verified at review time ✓",
      pieces: [
        "**The deal:** New York → Lisbon returns just dropped 41% for late-November dates — the deepest verified transatlantic discount this week.",
        "**Why now:** Shoulder-season pricing + a new route launch on the same corridor. Fare trackers show the drop holding for roughly 48 hours.",
        "**Evidence:** 9 sources · fares cross-checked on 2 independent trackers · no cross-source price disagreement.",
        "**Reader angle:** Book the flight now, plan the trip later — these dates sit in Lisbon's mildest, quietest month.",
      ]},
    { id: "carousel", label: "Carousel", icon: "🎠", maker: "hue", kind: "slides", verdict: "Prices match briefing exactly ✓", pieces: [],
      slides: [
        { kicker: "TRAVEL BRIEF · DEAL OF THE WEEK", title: "NYC → Lisbon, −41%", body: "The deepest verified transatlantic drop this week. Here's the deal, the dates, and the catch (there's barely one).", g1: "#FB923C", g2: "#EC4899" },
        { kicker: "THE DATES", title: "Late November wins", body: "Shoulder season: mild weather, thin crowds, and fares that don't make your eyes water.", g1: "#F97316", g2: "#F59E0B" },
        { kicker: "WHY IT DROPPED", title: "A new route shook prices", body: "A fresh competitor on the corridor forced everyone's hand. Travelers collect the winnings.", g1: "#EC4899", g2: "#7C6CF0" },
        { kicker: "THE CLOCK", title: "≈48 hours at this price", body: "Fare history says drops like this heal fast. Book the flight, plan the trip later.", g1: "#0EA47A", g2: "#38BDF8" },
        { kicker: "THE TAKE", title: "Set alerts, not alarms", body: "Follow Travel Brief — one verified deal a day, never a fake 'sale'. Sources in the first comment.", g1: "#E11D48", g2: "#F97316" },
      ]},
    { id: "linkedin_post", label: "LinkedIn Post", icon: "💼", maker: "herald", kind: "text", verdict: "No stale prices ✓",
      pieces: [
        "A 41% fare drop to Lisbon just opened for late November — verified twice, gone in ~48 hours.\n\nShoulder season is the frequent flyer's cheat code: mild weather, empty streets, honest prices.",
        "Why it dropped: a new route launch forced the whole corridor to compete.\n\nDeal, dates, and fare history in the carousel. Where would you go if the flight was the easy part?",
      ]},
    { id: "email", label: "Email", icon: "✉️", maker: "herald", kind: "text", verdict: "Urgency is factual, not manufactured ✓",
      pieces: [
        "**Subject:** Lisbon is 41% off — for about 48 hours ✈️",
        "Hi there —\n\nVerified deal, straight in: NYC → Lisbon returns dropped 41% for late-November dates, cross-checked on two fare trackers.",
        "Why it dropped, which dates work, and how long it usually lasts — all in today's brief.\n\n**→ See the deal**\n\nHappy travels,\nTravel Brief",
      ]},
  ],
  events: [], durationMs: 26000,
};

TRAVEL_FIXTURE.events = [
  A(0, "supervisor", "New continent, same dream team. Travel Playbook loaded!"),
  T(500, "supervisor", { name: "mcp · filesystem", detail: "read_playbook(travel-news)", result: "Playbook loaded · rubric Deal Value ×0.35 · 4 artifacts queued" }),
  D(1200, "supervisor", "Pixel — find me a deal worth packing for."),
  E(1300, "supervisor-scout"),
  A(1400, "scout", "Trading the newsroom for the departure board…"),
  T(1800, "scout", { name: "mcp · tavily-search", detail: "search('flight deals this week', travel)", result: "9 sources · 3 candidate deals" }),
  T(3200, "scout", { name: "mcp · fetch", detail: "fare trackers ×2, cross-check prices", result: "Lisbon fare confirmed on both trackers" }),
  D(4800, "scout", "A 41% drop to Lisbon. I already packed a tiny suitcase."),
  E(5000, "scout-curator"),
  A(5100, "curator", "Deals get scored like stories. Fake sales get binned like shrug stories."),
  T(5600, "curator", { name: "score_candidates", detail: "rubric · Deal Value ×0.35, Urgency ×0.25", result: "3 deals scored · Lisbon runs away with it" }),
  { t: 6400, kind: "scores", candidates: TRAVEL_FIXTURE.candidates },
  D(7600, "curator", "93 points. The '60% off*' resort sale scored 38 — off a price nobody ever paid."),
  E(7800, "curator-archivist"),
  A(7900, "archivist", "Checking the vault: have we sent everyone to Lisbon before? …Once. In May. Different deal."),
  T(8400, "archivist", { name: "rag · retrieve", detail: "brand-voice + past-runs", result: "No duplicate deal · style pack ready" }),
  D(9400, "archivist", "Clear to create. Makers — same graph, new sky. GO."),
  E(9600, "archivist-makers"),
  A(9700, "scribe", "Deal briefing: facts first, wanderlust second."),
  A(9700, "hue", "Sunset theme! Finally, my warm era."),
  A(9700, "herald", "Tailoring for travellers now. Same hands, new accent."),
  T(10200, "hue", { name: "mcp · carousel", detail: "render_carousel(spec, sunset)", result: "Renderer warm · theme sunset" }),
  PC(10800, "briefing", 0), P(10800, "scribe", 25),
  PC(11400, "carousel", 0), P(11400, "hue", 20),
  PC(12000, "linkedin_post", 0), P(12000, "herald", 35),
  PC(12600, "briefing", 1), PC(13200, "carousel", 1), P(13200, "hue", 40),
  PC(13800, "briefing", 2), PC(14400, "email", 0), P(14400, "herald", 60),
  PC(15000, "carousel", 2), P(15000, "hue", 60),
  PC(15600, "briefing", 3), D(16200, "scribe", "Briefing sealed. Every price double-checked."),
  PC(16400, "carousel", 3), PC(17000, "linkedin_post", 1),
  PC(17600, "carousel", 4), D(18000, "hue", "Five slides of pure golden hour."),
  PC(18400, "email", 1), PC(19000, "email", 2), D(19400, "herald", "Post + email tailored. Vera — check my prices, I dare you."),
  E(19600, "makers-reviewer"),
  A(19700, "reviewer", "Prices, dates, claims. In that order. Then joy."),
  T(20200, "reviewer", { name: "verify_claims", detail: "claims + fares → sources", result: "11 claims grounded · fares match at review time" }),
  { t: 21600, kind: "review", verdict: "PASS", notes: ["11/11 claims grounded", "Fares re-verified — no stale prices", "No duplicate deal in past runs", "Urgency is factual (≈48h fare history)"] },
  D(22200, "reviewer", "PASS. Even the urgency is honest. I'm almost emotional."),
  A(22600, "supervisor", "Same agents, new industry, zero code changed. That's the Playbook trick. ✨"),
  { t: 23000, kind: "phase", phase: "awaiting" },
];

export const FIXTURES: Record<string, RunFixture> = { "ai-news-gtm": AI_FIXTURE, "travel-news": TRAVEL_FIXTURE };
