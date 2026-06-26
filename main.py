import io
import json
import re

import ollama
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="City Watch",
    page_icon="CW",
    layout="centered",
)


# ──────────────────────────────────────────────────────────────────────────────
# GLOBE BACKGROUND (embedded HTML/JS component)
# ──────────────────────────────────────────────────────────────────────────────

GLOBE_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
        html,
        body {
            width: 100%;
            height: 100%;
            margin: 0;
            overflow: hidden;
            background: #010305;
        }

        canvas {
            display: block;
            width: 100vw;
            height: 100vh;
        }
    </style>
</head>
<body>
    <canvas id="globe" aria-hidden="true"></canvas>

    <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
    <script src="https://cdn.jsdelivr.net/npm/topojson-client@3"></script>
    <script>
        const canvas = document.getElementById("globe");
        const ctx = canvas.getContext("2d");
        const projection = d3.geoOrthographic().precision(0.15);
        const path = d3.geoPath(projection, ctx);
        const sphere = { type: "Sphere" };
        const graticule = d3.geoGraticule10();
        const fallbackTarget = { lat: 39.8283, lon: -98.5795 };

        let land = null;
        let borders = null;
        let target = fallbackTarget;
        let worldReady = false;

        // ── Star twinkle state ──
        const STAR_COUNT = 250;
        const stars = [];
        for (let i = 0; i < STAR_COUNT; i++) {
            stars.push({
                x: Math.sin(i * 131.71) * 0.5 + 0.5,
                y: Math.sin(i * 43.31) * 0.5 + 0.5,
                baseRadius: i % 7 === 0 ? 1.2 : 0.65,
                phase: Math.random() * Math.PI * 2,
                speed: 0.6 + Math.random() * 1.2,
                depth: 0.25 + Math.random() * 0.35,
            });
        }

        // ── Spinning state ──
        let spinAngle = 0;
        const SPIN_SPEED = 0.08; // Slow spin speed (degrees per frame)
        let lastTime = Date.now();

        function pinIframeToViewport() {
            const frame = window.frameElement;
            if (!frame) {
                return;
            }

            Object.assign(frame.style, {
                position: "fixed",
                inset: "0",
                width: "100vw",
                height: "100vh",
                border: "0",
                zIndex: "0",
                pointerEvents: "none",
            });

            if (frame.parentElement) {
                frame.parentElement.style.height = "0";
                frame.parentElement.style.overflow = "visible";
            }
        }

        function clamp(value, min, max) {
            return Math.min(max, Math.max(min, value));
        }

        function lerp(start, end, amount) {
            return start + (end - start) * amount;
        }

        function easeInOutCubic(value) {
            return value < 0.5
                ? 4 * value * value * value
                : 1 - Math.pow(-2 * value + 2, 3) / 2;
        }

        function getParentContext() {
            try {
                return {
                    document: window.parent.document,
                    window: window.parent,
                };
            } catch {
                return null;
            }
        }

        function getMarkerProgress(context) {
            const startMarker = context.document.getElementById("globe-scroll-start");
            const endMarker = context.document.getElementById("globe-scroll-end");

            if (!startMarker || !endMarker) {
                return null;
            }

            const viewportHeight = context.window.innerHeight || window.innerHeight;
            const startTop = startMarker.getBoundingClientRect().top;
            const endTop = endMarker.getBoundingClientRect().top;
            const markerDistance = Math.max(endTop - startTop, viewportHeight * 0.8);
            const travelDistance = Math.max(markerDistance * 0.72, viewportHeight * 0.58);

            return clamp(-startTop / travelDistance, 0, 1);
        }

        function getScrollerProgress(context) {
            const document = context.document;
            const viewportHeight = context.window.innerHeight || window.innerHeight;
            const candidates = [
                document.querySelector("[data-testid='stAppViewContainer']"),
                document.querySelector("[data-testid='stMain']"),
                document.scrollingElement,
                document.documentElement,
                document.body,
            ].filter(Boolean);

            for (const candidate of candidates) {
                const scrollTop = candidate.scrollTop || 0;
                if (scrollTop > 0) {
                    return clamp(scrollTop / (viewportHeight * 0.9), 0, 1);
                }
            }

            return clamp((context.window.scrollY || 0) / (viewportHeight * 0.9), 0, 1);
        }

        function getParentScrollProgress() {
            const context = getParentContext();
            if (!context) {
                return 0;
            }

            const markerProgress = getMarkerProgress(context);
            if (markerProgress !== null) {
                return markerProgress;
            }

            return getScrollerProgress(context);
        }

        function resizeCanvas() {
            const ratio = Math.min(window.devicePixelRatio || 1, 2);
            const width = window.innerWidth;
            const height = window.innerHeight;

            if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
                canvas.width = Math.round(width * ratio);
                canvas.height = Math.round(height * ratio);
                canvas.style.width = `${width}px`;
                canvas.style.height = `${height}px`;
            }

            ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
            return { width, height };
        }

        async function locateByIp() {
            const services = [
                {
                    url: "https://ipapi.co/json/",
                    parse: (data) => ({
                        lat: Number(data.latitude),
                        lon: Number(data.longitude),
                    }),
                },
                {
                    url: "https://ipwho.is/",
                    parse: (data) => ({
                        lat: Number(data.latitude),
                        lon: Number(data.longitude),
                    }),
                },
            ];

            for (const service of services) {
                try {
                    const response = await fetch(service.url, { cache: "no-store" });
                    if (!response.ok) {
                        continue;
                    }

                    const point = service.parse(await response.json());
                    if (Number.isFinite(point.lat) && Number.isFinite(point.lon)) {
                        return point;
                    }
                } catch {
                    continue;
                }
            }

            return fallbackTarget;
        }

        async function loadWorld() {
            const response = await fetch("https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json");
            const world = await response.json();

            land = topojson.feature(world, world.objects.land);
            borders = topojson.mesh(world, world.objects.countries, (a, b) => a !== b);
            worldReady = true;
        }

        function drawBackground(width, height) {
            const styles = getComputedStyle(document.documentElement);
            const bgColor = styles.getPropertyValue('--globe-bg').trim() || '#010305';

            ctx.fillStyle = bgColor;
            ctx.fillRect(0, 0, width, height);

            // ── Twinkling stars ──
            const now = Date.now() / 1000;
            ctx.fillStyle = "#ffffff";
            for (let i = 0; i < stars.length; i++) {
                const s = stars[i];
                const x = s.x * width;
                const y = s.y * height;
                const twinkle = Math.sin(now * s.speed + s.phase);
                const alpha = clamp(0.42 + twinkle * s.depth, 0.04, 1.0);
                const radius = s.baseRadius * (1 + twinkle * 0.10);
                ctx.save();
                ctx.globalAlpha = alpha;
                ctx.beginPath();
                ctx.arc(x, y, radius, 0, Math.PI * 2);
                ctx.fill();
                ctx.restore();
            }
        }

        function drawLocationMarker(rotation, progress) {
            const opacity = clamp((progress - 0.58) / 0.42, 0, 1);
            if (opacity <= 0) {
                return;
            }

            const center = [-rotation[0], -rotation[1]];
            const distance = d3.geoDistance([target.lon, target.lat], center);
            if (distance > Math.PI / 2) {
                return;
            }

            const point = projection([target.lon, target.lat]);
            if (!point) {
                return;
            }

            const pulse = 8 + Math.sin(Date.now() / 360) * 3;

            ctx.save();
            ctx.globalAlpha = opacity;
            ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
            ctx.fillStyle = "#ffffff";
            ctx.lineWidth = 1.5;

            ctx.beginPath();
            ctx.arc(point[0], point[1], pulse, 0, Math.PI * 2);
            ctx.stroke();

            ctx.beginPath();
            ctx.arc(point[0], point[1], 3.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
        }

        function drawGlobe() {
            pinIframeToViewport();

            const { width, height } = resizeCanvas();
            const progress = getParentScrollProgress();
            const acceleratedProgress = clamp(progress * 1.05, 0, 1);
            const eased = easeInOutCubic(acceleratedProgress);

            // ── Update spinning only when not scrolling ──
            const currentTime = Date.now();
            const deltaTime = (currentTime - lastTime) / 1000; // seconds
            lastTime = currentTime;
            if (progress === 0) {
                spinAngle += SPIN_SPEED * deltaTime * 60; // Normalize to ~60fps
            }

            drawBackground(width, height);

            const styles = getComputedStyle(document.documentElement);
            const oceanColor = styles.getPropertyValue('--globe-ocean').trim() || '#02070a';
            const landColor = styles.getPropertyValue('--globe-land').trim() || 'rgba(255, 255, 255, 0.035)';
            const borderColor = styles.getPropertyValue('--globe-border').trim() || 'rgba(255, 255, 255, 0.78)';
            const glowColor = styles.getPropertyValue('--globe-glow').trim() || 'rgba(62, 211, 255, 0.24)';

            const startRotation = [28, -12, 0];
            const targetRotation = [-target.lon, -target.lat, 0];
            
            // ── Calculate shortest rotation path ──
            let currentLon = startRotation[0] - spinAngle;
            let targetLon = targetRotation[0];
            
            // Normalize angles to [-180, 180]
            const normalizeAngle = (angle) => {
                while (angle > 180) angle -= 360;
                while (angle < -180) angle += 360;
                return angle;
            };
            
            currentLon = normalizeAngle(currentLon);
            targetLon = normalizeAngle(targetLon);
            
            // Find shortest path
            let lonDiff = targetLon - currentLon;
            if (lonDiff > 180) lonDiff -= 360;
            if (lonDiff < -180) lonDiff += 360;
            
            const rotation = [
                currentLon + lonDiff * eased,
                lerp(startRotation[1], targetRotation[1], eased),
                0,
            ];

            const baseRadius = Math.min(width, height) * 0.52;
            const closeRadius = Math.max(width, height) * 1.85;
            const radius = lerp(baseRadius, closeRadius, eased);
            const centerY = lerp(height + radius * 0.08, height * 0.5, eased);

            projection
                .scale(radius)
                .translate([width / 2 - 25, centerY])
                .rotate(rotation);

            const glow = ctx.createRadialGradient(
                width / 2,
                centerY,
                radius * 0.88,
                width / 2,
                centerY,
                radius * 1.12
            );
            glow.addColorStop(0, glowColor.replace('0.24', '0'));
            glow.addColorStop(0.72, glowColor.replace('0.24', '0.02'));
            glow.addColorStop(1, glowColor);

            ctx.save();
            ctx.beginPath();
            path(sphere);
            ctx.fillStyle = glow;
            ctx.fill();
            ctx.restore();

            ctx.save();
            ctx.beginPath();
            path(sphere);
            ctx.fillStyle = oceanColor;
            ctx.fill();
            ctx.clip();

            ctx.beginPath();
            path(graticule);
            ctx.strokeStyle = `rgba(255, 255, 255, ${lerp(0.10, 0.05, progress)})`;
            ctx.lineWidth = 0.55;
            ctx.stroke();

            if (worldReady) {
                ctx.beginPath();
                path(land);
                ctx.fillStyle = landColor;
                ctx.fill();

                ctx.beginPath();
                path(land);
                ctx.strokeStyle = borderColor;
                ctx.lineWidth = lerp(0.9, 1.2, progress);
                ctx.stroke();

                ctx.beginPath();
                path(borders);
                ctx.strokeStyle = borderColor.replace('0.78', '0.20').replace('0.4', '0.10');
                ctx.lineWidth = 0.45;
                ctx.stroke();
            }

            ctx.restore();

            ctx.beginPath();
            path(sphere);
            ctx.strokeStyle = borderColor;
            ctx.lineWidth = lerp(2.1, 0.9, progress);
            ctx.stroke();

            drawLocationMarker(rotation, progress);
            requestAnimationFrame(drawGlobe);
        }

        Promise.allSettled([loadWorld(), locateByIp()]).then((results) => {
            if (results[1].status === "fulfilled") {
                target = results[1].value;
            }
            drawGlobe();
        });
    </script>
</body>
</html>
"""


# ──────────────────────────────────────────────────────────────────────────────
# DESIGN / STYLING (CSS injected via st.markdown)
# ──────────────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800&display=swap');

    :root {
        --page-bg: #010305;
        --panel: rgba(4, 9, 13, 0.74);
        --panel-strong: rgba(8, 15, 21, 0.88);
        --line: rgba(255, 255, 255, 0.14);
        --text: #f7fbff;
        --muted: #9aa8b8;
        --accent: #5bdaff;
        --accent-warm: #f5c469;
        --font-family: "Poppins", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        --title-font: "Poppins", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        --globe-bg: #010305;
        --globe-ocean: #02070a;
        --globe-land: rgba(255, 255, 255, 0.035);
        --globe-border: rgba(255, 255, 255, 0.78);
        --globe-glow: rgba(62, 211, 255, 0.24);
    }

    [data-theme="light"] {
        --page-bg: #f5f7fa;
        --panel: rgba(255, 255, 255, 0.85);
        --panel-strong: rgba(255, 255, 255, 0.95);
        --line: rgba(0, 0, 0, 0.12);
        --text: #1a1a2e;
        --muted: #4a5568;
        --accent: #0066cc;
        --accent-warm: #d97706;
        --globe-bg: #e8ecf1;
        --globe-ocean: #d4d9e0;
        --globe-land: rgba(0, 0, 0, 0.08);
        --globe-border: rgba(0, 0, 0, 0.4);
        --globe-glow: rgba(0, 102, 204, 0.15);
    }

    /* ── Base ── */
    html { scroll-behavior: smooth; }
    .stApp { font-family: var(--font-family); background: var(--page-bg); color: var(--text); }
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"] { background: transparent; }
    [data-testid="stHeader"], header, footer, #MainMenu { visibility: hidden; height: 0 !important; }
    .block-container { position: relative; z-index: 2; max-width: 860px; padding-top: 0; padding-bottom: 5rem; }

    /* ── Hero ── */
    .front-hero {
        min-height: 32vh; width: 100vw; margin-left: calc(50% - 50vw);
        display: flex; align-items: flex-end; justify-content: center;
        text-align: center; padding-bottom: 0.25rem; box-sizing: border-box;
        animation: heroFadeIn 1.2s cubic-bezier(0.16, 1, 0.3, 1) both;
    }
    .hero-stack { display: flex; flex-direction: column; align-items: center; gap: 1.15rem; width: max-content; }
    .globe-scroll-marker { width: 0; height: 0; overflow: hidden; }
    .hero-title {
        color: var(--text); font-family: var(--title-font); font-size: 220px !important;
        line-height: 0.95; font-weight: 700; letter-spacing: -1px; margin: 0;
        text-shadow: 0 0 16px rgba(255,255,255,0.16), 0 8px 30px rgba(91,218,255,0.16), 0 18px 42px rgba(0,0,0,0.62);
    }

    /* ── Scroll indicator ── */
    .globe-runway {
        min-height: 66vh; width: 100vw; margin-left: calc(50% - 50vw);
        display: flex; justify-content: center; align-items: flex-end;
        padding-bottom: 1rem; box-sizing: border-box;
    }
    .scroll-indicator {
        color: var(--muted); font-family: var(--font-family); display: flex; flex-direction: column;
        align-items: center; gap: 0.45rem; font-size: 0.92rem; font-weight: 500;
        transition: opacity 0.3s ease;
    }
    .scroll-indicator strong {
        color: var(--text); font-size: 1.3rem; line-height: 1;
        animation: floatArrow 1.6s ease-in-out infinite;
    }

    /* ── Steps ── */
    .step-header { display: flex; align-items: center; gap: 1rem; margin-top: 3rem; margin-bottom: 1.2rem; }
    .step-num {
        width: 34px; height: 34px; border-radius: 999px;
        border: 1px solid var(--line); color: var(--text);
        display: flex; align-items: center; justify-content: center;
        font-size: 1rem; font-weight: 700;
        background: rgba(255,255,255,0.08); box-shadow: inset 0 0 18px rgba(91,218,255,0.18);
    }
    .step-title { color: var(--text); font-family: var(--font-family); font-size: 1.42rem; font-weight: 650; letter-spacing: 0; }

    /* ── Form elements ── */
    div[data-testid="stTextArea"],
    div[data-testid="stTextInput"],
    div[data-testid="stForm"] {
        background: var(--panel); backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
        border: 1px solid var(--line); border-radius: 8px;
        padding: 1.35rem; margin-bottom: 1.6rem;
        box-shadow: 0 14px 42px rgba(0,0,0,0.38);
        transition: border-color 0.25s ease, box-shadow 0.25s ease;
    }
    div[data-testid="stTextArea"]:hover,
    div[data-testid="stTextInput"]:hover {
        border-color: var(--accent); box-shadow: 0 16px 48px rgba(0,0,0,0.46);
    }
    div.stButton > button[kind="primary"] {
        width: 100%; min-height: 3.2rem;
        background: var(--text) !important; border: 1px solid var(--line) !important;
        border-radius: 8px !important; box-shadow: 0 12px 30px rgba(0,0,0,0.34) !important;
        color: var(--page-bg) !important; font-family: var(--font-family) !important;
        font-size: 1.03rem !important; font-weight: 750 !important;
        transition: transform 0.25s ease, box-shadow 0.25s ease !important;
    }
    div.stButton > button[kind="primary"]:hover {
        transform: translateY(-2px); box-shadow: 0 16px 38px rgba(0,0,0,0.48) !important;
    }
    div[data-testid="stFileUploader"] { width: 100%; max-width: none; margin-bottom: 1.6rem; }
    div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] {
        width: 100% !important; max-width: none !important; min-height: 112px;
        background: var(--panel); border: 1px solid var(--line);
        border-radius: 8px; box-shadow: 0 14px 42px rgba(0,0,0,0.38); box-sizing: border-box;
    }
    div[data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"]:hover {
        border-color: var(--accent); box-shadow: 0 16px 48px rgba(0,0,0,0.46);
    }
    div[data-baseweb="textarea"],
    div[data-baseweb="input"] {
        background-color: rgba(0,0,0,0.30) !important;
        border: 1px solid var(--line) !important;
        border-radius: 8px !important; color: var(--text) !important;
        font-family: var(--font-family) !important;
    }
    div[data-baseweb="textarea"]:focus-within,
    div[data-baseweb="input"]:focus-within { border-color: var(--accent) !important; }
    div[data-testid="stNotification"] {
        background: var(--panel-strong) !important; border: 1px solid var(--line) !important;
        border-radius: 8px !important; color: var(--text) !important;
        font-family: var(--font-family) !important;
        animation: fadeInUp 0.45s ease-out both;
    }

    /* ── Utility ── */
    .fade-in { animation: fadeInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) both; }

    /* ── Keyframes ── */
    @keyframes heroFadeIn {
        from { opacity: 0; transform: translateY(28px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(20px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes floatArrow {
        0%, 100% { transform: translateY(0); }
        50%      { transform: translateY(3px); }
    }

    /* ── Mobile ── */
    @media (max-width: 700px) {
        .block-container { padding-left: 1.1rem; padding-right: 1.1rem; }
        .front-hero { min-height: 30vh; }
        .hero-title { font-size: 120px !important; line-height: 1; }
        .globe-runway { min-height: 66vh; padding-bottom: 1rem; }
        .step-title { font-size: 1.18rem; }
    }

    /* ── Streamlit font overrides ── */
    * { font-family: var(--font-family) !important; }
    [data-testid="stMarkdownContainer"],
    [data-testid="stText"],
    [data-testid="stCaption"],
    [data-testid="stHeading"],
    [data-testid="stSubheader"],
    label,
    .stMarkdown,
    .stText {
        font-family: var(--font-family) !important;
    }
    [data-testid="stIconMaterial"] {
        font-family: "Material Symbols Rounded" !important;
        font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 24 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

MODEL_NAME = "llava:latest"


# ──────────────────────────────────────────────────────────────────────────────
# IMAGE PREPARATION
# ──────────────────────────────────────────────────────────────────────────────

def prepare_image_for_ai(uploaded_photo):
    uploaded_photo.seek(0)
    image = Image.open(uploaded_photo).convert("RGB")
    image.thumbnail((640, 640))
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="JPEG", quality=75)
    uploaded_photo.seek(0)
    return image_buffer.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# AI ANALYSIS
# ──────────────────────────────────────────────────────────────────────────────

def ensure_model_is_available():
    ollama.pull(MODEL_NAME, stream=False)


def extract_json_object(text):
    if not text:
        raise ValueError("Empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found")
    return json.loads(match.group(0))


def analyze_hazard_with_ai(uploaded_photo, description, location, start_time):
    image_bytes = prepare_image_for_ai(uploaded_photo)

    description_text = description.strip() if description.strip() else "No written description was provided."
    start_time_text = start_time.strip() if start_time.strip() else "The start time was not provided."

    prompt = f"""
You are City Watch, an AI system that analyzes photographs of urban hazards.

A resident submitted a photograph of a possible city infrastructure
or public-safety problem.

Resident description:
{description_text}

Reported location:
{location}

Reported start time:
{start_time_text}

Carefully inspect the uploaded photograph.

Identify the most likely visible issue. Possible examples include:

- pothole
- flooding
- fallen tree
- blocked sidewalk
- broken streetlight
- damaged fire hydrant
- overflowing garbage
- damaged traffic sign
- exposed electrical equipment
- damaged roadway
- another public infrastructure hazard

Return only valid JSON with exactly these fields:

{{
    "issue_identification": "Specific name of the issue",
    "danger_level": "Low, Medium, High, or Critical",
    "priority_score": 75,
    "confidence": 90,
    "visible_evidence": "Specific details visible in the photograph",
    "safety_recommendation": "How residents should safely avoid the hazard",
    "appropriate_authority": "The department or authority that should respond",
    "recommended_city_action": "What the city department should do",
    "service_report": "A concise professional service report",
    "reasoning": "Why this danger level and priority score were assigned"
}}

Rules:

1. Use the photograph as the main source of evidence.
2. Use the written description only as supporting context.
3. Do not invent injuries, leaks, fires, or damage that are not visible.
4. If the photograph is unclear, lower the confidence score.
5. Danger level must be Low, Medium, High, or Critical.
6. Use Critical only for an apparent immediate threat to life.
7. Priority score must be an integer from 0 to 100.
8. Confidence must be an integer from 0 to 100.
9. Never tell residents to touch, move, or repair dangerous infrastructure.
10. Return JSON only. Do not use Markdown.
"""

    try:
        ensure_model_is_available()
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt, "images": [image_bytes]}],
            format="json",
            options={"temperature": 0.1, "num_predict": 400},
            keep_alive="10m"
        )
        response_text = response["message"]["content"]
        analysis = extract_json_object(response_text)
        if not isinstance(analysis, dict):
            raise RuntimeError("The AI response was valid JSON, but it was not a JSON object.")
        return analysis
    except json.JSONDecodeError:
        raise RuntimeError("The AI responded, but its response was not valid JSON.")
    except ollama.ResponseError as error:
        raise RuntimeError(f"Ollama rejected the request: {error.error}")
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(f"AI analysis failed: {error}")


# ──────────────────────────────────────────────────────────────────────────────
# SERVICE REPORT FORMATTING
# ──────────────────────────────────────────────────────────────────────────────

def create_service_report_text(analysis, location, start_time):
    report_date = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    reported_start = start_time.strip() if start_time.strip() else "Not provided"

    return f"""CITY WATCH HAZARD SERVICE REPORT

REPORT INFORMATION
Generated: {report_date}
Location: {location}
Reported Start Time: {reported_start}

INCIDENT CLASSIFICATION
Issue: {analysis.get("issue_identification", "Unknown issue")}
Danger Level: {analysis.get("danger_level", "Unknown")}
Priority Score: {analysis.get("priority_score", 0)}/100
AI Confidence: {analysis.get("confidence", 0)}%

RESPONSIBLE AUTHORITY
{analysis.get("appropriate_authority", "Unknown authority")}

INCIDENT SUMMARY
{analysis.get("service_report", "No service-report summary was returned.")}

VISIBLE EVIDENCE
{analysis.get("visible_evidence", "No visible evidence was provided.")}

RECOMMENDED CITY RESPONSE
{analysis.get("recommended_city_action", "No city action was provided.")}

RESIDENT SAFETY GUIDANCE
{analysis.get("safety_recommendation", "No safety recommendation was provided.")}

NOTICE
This report was generated by the City Watch prototype and should be
reviewed by an authorized city employee before official action is taken.
"""


# ──────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

def render_step_header(number: int, title: str, fade: bool = False) -> None:
    fade_class = " fade-in" if fade else ""
    st.markdown(
        f"""
        <div class="step-header{fade_class}">
            <div class="step-num">{number}</div>
            <div class="step-title">{title}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# SCROLL-FADE & AUTO-SCROLL SCRIPTS
# ──────────────────────────────────────────────────────────────────────────────

SCROLL_FADE_JS = """
<script>
(function() {
    function attachScrollFade() {
        var indicator = document.querySelector('.scroll-indicator');
        if (!indicator) { setTimeout(attachScrollFade, 300); return; }

        var scrollContainer = null;
        var candidates = [
            document.querySelector("[data-testid='stAppViewContainer']"),
            document.querySelector("[data-testid='stMain']"),
            document.querySelector("section.main"),
            document.scrollingElement,
            document.documentElement
        ];
        for (var i = 0; i < candidates.length; i++) {
            if (candidates[i] && candidates[i].scrollHeight > candidates[i].clientHeight) {
                scrollContainer = candidates[i];
                break;
            }
        }
        if (!scrollContainer) scrollContainer = document.documentElement;

        function updateOpacity() {
            var rect = indicator.getBoundingClientRect();
            var vh = window.innerHeight;
            var ratio = rect.top / vh;
            var opacity;
            if (ratio >= 0.70) { opacity = 1; }
            else if (ratio <= 0.30) { opacity = 0; }
            else { opacity = (ratio - 0.30) / 0.40; }
            indicator.style.opacity = Math.max(0, Math.min(1, opacity));
        }

        scrollContainer.addEventListener('scroll', updateOpacity, { passive: true });
        window.addEventListener('scroll', updateOpacity, { passive: true });
        function loop() { updateOpacity(); requestAnimationFrame(loop); }
        requestAnimationFrame(loop);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attachScrollFade);
    } else {
        setTimeout(attachScrollFade, 100);
    }
})();
</script>
"""

AUTO_SCROLL_JS = """
<script>
(function() {
    function attachAutoScroll() {
        const stepHeaders = document.querySelectorAll('.step-header');
        if (stepHeaders.length === 0) { setTimeout(attachAutoScroll, 300); return; }

        let scrollContainer = null;
        const candidates = [
            document.querySelector("[data-testid='stAppViewContainer']"),
            document.querySelector("[data-testid='stMain']"),
            document.querySelector("section.main"),
            document.scrollingElement,
            document.documentElement
        ];
        for (let i = 0; i < candidates.length; i++) {
            if (candidates[i] && candidates[i].scrollHeight > candidates[i].clientHeight) {
                scrollContainer = candidates[i];
                break;
            }
        }
        if (!scrollContainer) scrollContainer = document.documentElement;

        function scrollToStep(stepIndex) {
            if (stepHeaders[stepIndex]) {
                const targetY = stepHeaders[stepIndex].getBoundingClientRect().top + scrollContainer.scrollTop - 100;
                scrollContainer.scrollTo({ top: targetY, behavior: 'smooth' });
            }
        }

        const fileUploader = document.querySelector('[data-testid="stFileUploader"] input[type="file"]');
        if (fileUploader) {
            fileUploader.addEventListener('change', function() {
                if (this.files.length > 0) { setTimeout(() => scrollToStep(1), 500); }
            });
        }

        const textArea = document.querySelector('[data-testid="stTextArea"] textarea');
        if (textArea) {
            let hasTyped = false;
            textArea.addEventListener('input', function() {
                if (!hasTyped && this.value.length > 10) { hasTyped = true; setTimeout(() => scrollToStep(2), 500); }
            });
        }

        const locationInput = document.querySelector('[data-testid="stTextInput"] input');
        if (locationInput) {
            let hasTypedLocation = false;
            locationInput.addEventListener('input', function() {
                if (!hasTypedLocation && this.value.length > 5) { hasTypedLocation = true; setTimeout(() => scrollToStep(3), 500); }
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attachAutoScroll);
    } else {
        setTimeout(attachAutoScroll, 500);
    }
})();
</script>
"""


# ──────────────────────────────────────────────────────────────────────────────
# MAIN PAGE LAYOUT
# ──────────────────────────────────────────────────────────────────────────────

components.html(GLOBE_HTML, height=1)

st.markdown(
    """
    <div id="globe-scroll-start" class="globe-scroll-marker"></div>
    <section class="front-hero">
        <div class="hero-stack">
            <h1 class="hero-title" style="font-size: 220px !important;">City Watch</h1>
        </div>
    </section>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="globe-runway">
        <div class="scroll-indicator">
            <span>Scroll down to begin</span>
            <strong>&darr;</strong>
        </div>
    </div>
    <div id="globe-scroll-end" class="globe-scroll-marker"></div>
    """,
    unsafe_allow_html=True,
)
st.markdown(SCROLL_FADE_JS, unsafe_allow_html=True)
st.markdown(AUTO_SCROLL_JS, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# PHOTO UPLOAD
# ──────────────────────────────────────────────────────────────────────────────

render_step_header(1, "Upload a photo")

uploaded_photo = st.file_uploader(
    "Take or upload a clear photo of the city hazard",
    type=["jpg", "jpeg", "png", "webp"],
    help="Supported file types: JPG, JPEG, PNG, and WEBP."
)

if uploaded_photo is not None:
    try:
        uploaded_photo.seek(0)
        preview_image = Image.open(uploaded_photo)
        st.image(preview_image, caption="Uploaded city hazard", use_container_width=True)
        uploaded_photo.seek(0)
        st.success("Photo uploaded successfully.")
    except Exception as error:
        st.error(f"The image could not be opened: {error}")


# ──────────────────────────────────────────────────────────────────────────────
# OPTIONAL DESCRIPTION
# ──────────────────────────────────────────────────────────────────────────────

render_step_header(2, "Describe the issue")

description = st.text_area(
    "Optional description",
    placeholder="Example: The fire hydrant has been leaking into the road for about 20 minutes.",
    height=120,
    help="The description is optional, but it may help the AI better understand what is happening."
)


# ──────────────────────────────────────────────────────────────────────────────
# REPORT DETAILS
# ──────────────────────────────────────────────────────────────────────────────

render_step_header(3, "Add report details")

location = st.text_input(
    "Location",
    placeholder="Example: 5th Street and Pine Avenue"
)

start_time = st.text_input(
    "When did the problem start?",
    placeholder="Example: Around 3:15 PM or approximately 20 minutes ago"
)


# ──────────────────────────────────────────────────────────────────────────────
# SUBMIT BUTTON
# ──────────────────────────────────────────────────────────────────────────────

submit_button = st.button(
    "Analyze hazard with AI",
    type="primary",
    use_container_width=True
)


# ──────────────────────────────────────────────────────────────────────────────
# RUN THE AI
# ──────────────────────────────────────────────────────────────────────────────

if submit_button:

    if uploaded_photo is None:
        st.error("Please upload a photo before starting the AI analysis.")

    elif not location.strip():
        st.error("Please enter the location of the issue.")

    else:
        try:
            with st.spinner("City Watch AI is analyzing the photograph..."):
                analysis = analyze_hazard_with_ai(
                    uploaded_photo=uploaded_photo,
                    description=description,
                    location=location,
                    start_time=start_time
                )

            st.success("AI analysis completed.")

            render_step_header(4, "AI Analysis Results", fade=True)

            st.subheader(analysis.get("issue_identification", "Unknown issue"))

            column1, column2, column3 = st.columns(3)
            with column1:
                st.metric("Danger Level", analysis.get("danger_level", "Unknown"))
            with column2:
                st.metric("Priority Score", f'{analysis.get("priority_score", 0)}/100')
            with column3:
                st.metric("AI Confidence", f'{analysis.get("confidence", 0)}%')

            st.subheader("Visible Evidence")
            st.write(analysis.get("visible_evidence", "No visible-evidence explanation was returned."))

            st.subheader("Safety Recommendation")
            st.write(analysis.get("safety_recommendation", "No safety recommendation was returned."))

            st.subheader("Appropriate Authority")
            st.write(analysis.get("appropriate_authority", "Unknown"))

            st.subheader("Recommended City Action")
            st.write(analysis.get("recommended_city_action", "No recommended action was returned."))

            st.subheader("Generated Service Report")

            report_date = datetime.now().strftime("%B %d, %Y at %I:%M %p")
            reported_start = start_time.strip() if start_time.strip() else "Not provided"

            with st.container(border=True):
                st.markdown("### 🏙️ City Watch Hazard Service Report")
                st.caption(f"Generated {report_date}")

                report_column1, report_column2 = st.columns(2)

                with report_column1:
                    st.markdown("**Reported Location**")
                    st.write(location)
                    st.markdown("**Issue Classification**")
                    st.write(analysis.get("issue_identification", "Unknown issue"))
                    st.markdown("**Responsible Authority**")
                    st.write(analysis.get("appropriate_authority", "Unknown authority"))

                with report_column2:
                    st.markdown("**Reported Start Time**")
                    st.write(reported_start)
                    st.markdown("**Danger Level**")
                    st.write(analysis.get("danger_level", "Unknown"))
                    st.markdown("**Priority Score**")
                    st.write(f'{analysis.get("priority_score", 0)}/100')

                st.divider()

                st.markdown("#### Incident Summary")
                st.write(analysis.get("service_report", "No service-report summary was returned."))

                st.markdown("#### Visible Evidence")
                st.write(analysis.get("visible_evidence", "No visible evidence was returned."))

                st.markdown("#### Recommended Municipal Response")
                st.write(analysis.get("recommended_city_action", "No recommended city action was returned."))

                st.markdown("#### Resident Safety Guidance")
                st.write(analysis.get("safety_recommendation", "No safety guidance was returned."))

                st.divider()
                st.caption(
                    "This report was generated by the City Watch prototype. "
                    "It should be reviewed by an authorized city employee before official action is taken."
                )

            service_report_text = create_service_report_text(
                analysis=analysis,
                location=location,
                start_time=start_time
            )

            st.download_button(
                label="Download Service Report",
                data=service_report_text,
                file_name="city_watch_service_report.txt",
                mime="text/plain",
                use_container_width=True
            )

            st.subheader("AI Reasoning")
            st.write(analysis.get("reasoning", "No reasoning was returned."))

        except RuntimeError as error:
            st.error(str(error))