# main.py — COMPLETE UPDATED VERSION WITH ALL FEATURES
import os
import sys
import asyncio

# Fix for Windows asyncio loop (Must be before any other asyncio usage)
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import re
import urllib.parse
import json
import random
import shutil
import hashlib
from typing import List, Tuple, Dict, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, Form, Request, Depends, HTTPException, status, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.requests import Request as StarletteRequest # Renamed to avoid conflict with fastapi.Request
from starlette.datastructures import UploadFile as StarletteUploadFile # Renamed to avoid conflict with fastapi.UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile # Renamed to avoid conflict with fastapi.UploadFile
import uuid
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from utils import dom_diff
from sqlalchemy.orm import Session
from pydantic import BaseModel

from PIL import Image, ImageDraw, ImageFont
import imageio
import numpy as np
from playwright.async_api import async_playwright
import phonenumbers
from phonenumbers import PhoneNumberMatcher, PhoneNumberFormat, is_valid_number, format_number
import concurrent.futures
import functools
import httpx # Added for proxy

# Create a process pool for heavy CPU/IO tasks
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# Import database and models
import database
import models
import auth
from config import settings
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Create necessary directories
os.makedirs("screenshots", exist_ok=True)
os.makedirs("videos", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("temp_frames", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("diffs", exist_ok=True)

app = FastAPI()
# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
app.mount("/videos", StaticFiles(directory="videos"), name="videos")

# Favicon route
@app.get("/favicon.ico")
async def favicon():
    """Serve favicon"""
    from fastapi.responses import FileResponse
    return FileResponse("static/favicon.png")
app.mount("/diffs", StaticFiles(directory="diffs"), name="diffs")

templates = Jinja2Templates(directory="templates")

# ========== CUSTOM JINJA2 FILTERS ==========

def from_json(value):
    """Custom Jinja2 filter to parse JSON strings"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except:
            return []
    return value

# Add custom filters to Jinja2 environment
templates.env.filters['from_json'] = from_json

def to_json(value):
    """Custom Jinja2 filter to convert to JSON string"""
    return json.dumps(value)

templates.env.filters['to_json'] = to_json
# ===========================================

# Create database tables
models.Base.metadata.create_all(bind=database.engine)

# Global dictionary to track running tasks
running_tasks = {}

# Pydantic models for JSON requests
class LoginRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str

class GoogleLoginRequest(BaseModel):
    token: str

# ========== AUTHENTICATION MIDDLEWARE ==========

async def get_current_user_from_cookie(request: Request, db: Session = Depends(auth.get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        # Use the verify_token function from auth.py
        user_id = auth.verify_token(token)
        if not user_id:
            return None
        
        # Get user from database - ID is now String (UUID)
        user = db.query(models.User).filter(models.User.id == user_id).first()
        return user
    except Exception as e:
        print(f"Authentication error: {e}")
        return None

# ========== AUTHENTICATION DEPENDENCY ==========

async def require_auth(request: Request, db: Session = Depends(auth.get_db)):
    """Dependency to require authentication for protected routes."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    
    # Enable RLS for this request - REMOVED for SQLite
    # auth.set_db_session_user(db, user.id)
    
    return user

# ========== UNIQUE FILENAME FUNCTION ==========

def get_unique_filename(url: str) -> str:
    """Generate unique filename using last path segment + domain"""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    domain = re.sub(r'[^\w\.-]', '-', domain)
    
    path = parsed.path.strip("/")
    if not path or path in ("", "/"):
        page_name = "home"
    else:
        segments = [s for s in path.split("/") if s]
        if segments:
            page_name = segments[-1].split('.')[0]
            page_name = re.sub(r'[^\w\-]', '-', page_name).strip("-").lower()
            if not page_name or page_name in ("index", "home"):
                page_name = "home"
            if len(page_name) > 50:
                page_name = page_name[:47] + "..."
        else:
            page_name = "home"
    
    return f"{page_name}__{domain}"

# ========== STATIC AUDIT FUNCTIONS ==========

# ========== STATIC AUDIT FUNCTIONS ==========

async def capture_screenshots(urls: List[str], browsers: List[str], resolutions: List[Tuple[int, int]], session_id: str, user_id: int, db: Session, access_token: str = None):
    session_folder = f"screenshots/{session_id}"
    os.makedirs(session_folder, exist_ok=True)
    
    display_url_prefix = "/screenshots"
    config = { # This config dictionary was misplaced in the original code, moving it here.
        "urls": urls,
        "browsers": browsers,
        "resolutions": [f"{w}x{h}" for w, h in resolutions],
        "type": "static"
    }
    with open(f"{session_folder}/config.json", "w") as f:
        json.dump(config, f)

    try:
        async with async_playwright() as p:
            browser_map = {
                "Chrome": p.chromium,
                "Edge": p.chromium,
                "Firefox": p.firefox,
                "Safari": p.webkit
            }

            # AGGRESSIVE OPTIMIZATION: 5 URLs in parallel
            sem = asyncio.Semaphore(5)

            async def process_url(page, url, w, h, browser_name):
                unique = get_unique_filename(url)
                
                # Check if task was stopped
                session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                if session and session.status == "stopped":
                    return

                try:
                    await page.set_viewport_size({"width": w, "height": h})
                    
                    # 1. Smarter Navigation (Wait for DOM, then Network Idle with short timeout)
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        await page.wait_for_load_state("networkidle", timeout=5000) # Fast fail to keep moving
                    except:
                        pass

                    # 2. Optimized Hybrid Scroll (Lazy Load Trigger)
                    # Scrolls 1000px steps, stops if hits bottom. Fast.
                    await page.evaluate("""async () => {
                        await new Promise((resolve) => {
                            let totalHeight = 0;
                            const distance = 1000;
                            const timer = setInterval(() => {
                                const scrollHeight = document.body.scrollHeight;
                                window.scrollBy(0, distance);
                                totalHeight += distance;
                                if(totalHeight >= scrollHeight - window.innerHeight){
                                    clearInterval(timer);
                                    resolve();
                                }
                            }, 50); // Very fast scroll
                        });
                    }""")
                    
                    await page.wait_for_timeout(1000) # Short buffer
                    await page.evaluate("() => window.scrollTo(0, 0)")
                    await page.wait_for_timeout(500)

                    path = f"{session_folder}/{browser_name}/{unique}__{w}x{h}.png"
                    await page.screenshot(path=path, full_page=True)
                    
                    # Offload image processing (keep usage of original path for worker if needed, 
                    # but here we just optimize for upload/storage. 
                    # Worker `add_browser_frame` might expect PNG? 
                    # Let's check `add_browser_frame`. It opens image. Pillow opens webp fine.
                    # But we'll optimize AFTER capturing and BEFORE uploading.
                    
                    # OPTIMIZE: Convert to WebP
                    upload_path = path
                    upload_filename = os.path.basename(path)
                    content_type = "image/png"
                    
                    try:
                        webp_path = path.replace(".png", ".webp")
                        with Image.open(path) as img:
                            img.save(webp_path, "WEBP", quality=80, optimize=True)
                        
                        # Verify it saved
                        if os.path.exists(webp_path):
                            # Remove original PNG to save space
                            os.remove(path)
                            upload_path = webp_path
                            upload_filename = os.path.basename(webp_path)
                            content_type = "image/webp"
                    except Exception as opt_err:
                        print(f"Image Optimization Failed: {opt_err}")
                        # Fallback to PNG (path)

                    # Offload image processing (async worker)
                    loop = asyncio.get_running_loop()
                    # Updated to pass upload_path which might be WebP
                    await loop.run_in_executor(executor, add_browser_frame, upload_path, url)

                    # Update progress in database - Best effort
                    try:
                        # Local Path
                        screenshot_path = f"/screenshots/{session_id}/{browser_name}/{upload_filename}"
                        
                        # Save result
                        result_record = models.StaticAuditResult(
                            session_id=session_id,
                            url=url,
                            browser=browser_name,
                            resolution=f"{w}x{h}",
                            screenshot_path=screenshot_path,
                            filename=upload_filename # Store optimized filename
                        )
                        db.add(result_record)
                        
                        session.completed += 1
                        db.commit()
                    except:
                        db.rollback()

                    print(f"[STATIC][{browser_name}] {url} @ {w}x{h} — DONE")
                    
                except Exception as e:
                    print(f"[STATIC][{browser_name}] FAILED {url} @ {w}x{h}: {e}")

            async def run_browser(browser_name: str):
                os.makedirs(f"{session_folder}/{browser_name}", exist_ok=True)
                launch_args = {"headless": True}
                
                if browser_name == "Chrome":
                    launch_args["channel"] = "chrome"
                elif browser_name == "Edge":
                    launch_args["channel"] = "msedge"

                browser = await browser_map[browser_name].launch(**launch_args)
                context = await browser.new_context()
                
                tasks = []
                # Create a worker function to manage page lifecycle
                async def worker(url, w, h):
                    async with sem:
                        try:
                            page = await context.new_page()
                            await process_url(page, url, w, h, browser_name)
                            await page.close()
                        except Exception as e:
                            print(f"Worker error: {e}")

                for url in urls:
                    for w, h in resolutions:
                         tasks.append(worker(url, w, h))
                
                await asyncio.gather(*tasks)
                await context.close()
                await browser.close()

            await asyncio.gather(*[run_browser(b) for b in browsers])
            
        # Mark as completed
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Static audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    # Clean up running tasks
    if session_id in running_tasks:
        del running_tasks[session_id]
        
    print(f"STATIC SESSION {session_id} COMPLETED")

# ========== DYNAMIC AUDIT FUNCTIONS ==========

async def record_videos_async(urls: List[str], selected_browsers: List[str], 
                              selected_resolutions: List[Tuple[int, int]], 
                              session_id: str, user_id: int, db: Session, access_token: str = None):
    session_folder = f"videos/{session_id}"
    os.makedirs(session_folder, exist_ok=True)

    with open(f"{session_folder}/config.json", "w") as f:
        json.dump({
            "urls": urls,
            "browsers": selected_browsers,
            "resolutions": [f"{w}x{h}" for w, h in selected_resolutions],
            "type": "dynamic"
        }, f)

    try:
        async with async_playwright() as p:
            browser_map = {"Chrome": p.chromium, "Edge": p.chromium}

            # AGGRESSIVE OPTIMIZATION: 3 Videos in parallel (High cpu load)
            sem = asyncio.Semaphore(3)
            
            async def process_video(page, url, w, h, browser_name, unique_name):
                 # Check if task was stopped
                session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                if session and session.status == "stopped":
                    return

                try:
                    video_path_local = await record_fullpage_video(page, url, w, h, session_folder, browser_name, unique_name)
                    
                    # Video Path (Local)
                    video_url = f"/videos/{session_id}/{browser_name}/{os.path.basename(video_path_local)}"
                    
                    # Supabase upload removed - using local storage
                    print(f"[DYNAMIC] Final Video URL: {video_url}")
                    # Save result to DB
                    result = models.DynamicAuditResult(
                        session_id=session_id,
                        url=url,
                        browser=browser_name,
                        resolution=f"{w}x{h}",
                        video_path=video_url,
                        filename=os.path.basename(video_path_local)
                    )
                    db.add(result)

                    # Update progress in database - Best effort
                    try:
                        session.completed += 1
                        db.commit()
                    except:
                        db.rollback()
                            
                except Exception as e:
                    print(f"[DYNAMIC][{browser_name}] ERROR: {url} @ {w}x{h} → {e}")

            async def run_browser(browser_name: str):
                os.makedirs(f"{session_folder}/{browser_name}", exist_ok=True)
                browser = await browser_map[browser_name].launch(headless=True)
                
                # Create context
                context = await browser.new_context()
                
                tasks = []
                async def worker(url, w, h):
                    async with sem:
                        try:
                            page = await context.new_page()
                            unique_name = get_unique_filename(url)
                            await process_video(page, url, w, h, browser_name, unique_name)
                            await page.close()
                        except:
                            pass

                for url in urls:
                    for w, h in selected_resolutions:
                        tasks.append(worker(url, w, h))
                
                await asyncio.gather(*tasks)
                await context.close()
                await browser.close()

            await asyncio.gather(*[run_browser(name) for name in selected_browsers if name in browser_map])
            
        # Mark as completed
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Dynamic audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    # Clean up running tasks
    if session_id in running_tasks:
        del running_tasks[session_id]
        
    print(f"DYNAMIC SESSION {session_id} COMPLETED")

async def record_fullpage_video(page, url: str, w: int, h: int, session_folder: str, browser_name: str, unique_name: str):
    """Record a full-page video with scrolling and mouse movement."""
    try:
        await page.set_viewport_size({"width": w, "height": h})
        
        # 1. Smarter Navigation
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
             pass 
        
        # Short stabilization
        await asyncio.sleep(1.0)
        
        # Get page height for scrolling
        page_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = h
        
        # Optimized Scroll Steps: Larger steps, faster
        step_size = int(viewport_height * 0.9) 
        scroll_steps = max(1, page_height // step_size)
        
        frames_dir = f"temp_frames/{unique_name}_{browser_name}_{w}x{h}"
        os.makedirs(frames_dir, exist_ok=True)
        
        frame_count = 0
        
        # Record initial view
        await page.screenshot(path=f"{frames_dir}/frame_{frame_count:04d}.png")
        frame_count += 1
        
        # Simulate scrolling
        current_scroll = 0
        for step in range(scroll_steps + 1): 
            current_scroll += step_size
            if current_scroll > page_height:
                current_scroll = page_height
                
            await page.evaluate(f"window.scrollTo(0, {current_scroll})")
            
            # Very fast wait
            await asyncio.sleep(0.2)
            
            # Simple mouse wiggle
            mouse_x = random.randint(100, w - 100)
            mouse_y = random.randint(100, viewport_height - 100)
            await page.mouse.move(mouse_x, mouse_y)
            # No extra sleep, just capture
            
            # Take screenshot
            await page.screenshot(path=f"{frames_dir}/frame_{frame_count:04d}.png")
            frame_count += 1
            
            if current_scroll >= page_height:
                break
        
        # Scroll back to top
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=f"{frames_dir}/frame_{frame_count:04d}.png")
        frame_count += 1
        
        # Create video from frames
        video_path = f"{session_folder}/{browser_name}/{unique_name}__{w}x{h}.mp4"
        os.makedirs(os.path.dirname(video_path), exist_ok=True)
        
        # Use imageio to create video
        images = []
        for i in range(frame_count):
            img_path = f"{frames_dir}/frame_{i:04d}.png"
            if os.path.exists(img_path):
                images.append(imageio.imread(img_path))
        
        if images:
            # Offload video generation to thread pool
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                executor,
                functools.partial(imageio.mimsave, video_path, images, fps=3) # Higher FPS for smoother look
            )
            print(f"Video saved: {video_path}")
            
            # Clean up temp frames
            shutil.rmtree(frames_dir, ignore_errors=True)
            
            return video_path
        return None
        
    except Exception as e:
        print(f"Error recording video for {url}: {e}")
        raise

# ========== H1 AUDIT FUNCTIONS ==========

async def audit_h1_tags(urls: List[str], session_id: str, user_id: int, db: Session):
    """Audit H1 tags on multiple URLs"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            for i, url in enumerate(urls):
                try:
                    # Check if task was stopped
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped":
                        break
                    
                    await page.goto(url, wait_until="networkidle", timeout=90000)
                    await asyncio.sleep(2)  # Wait for page to load
                    
                    # Extract H1 tags
                    h1_elements = await page.evaluate('''() => {
                        const h1s = Array.from(document.querySelectorAll('h1'));
                        return h1s.map(h1 => ({
                            text: h1.textContent.trim(),
                            length: h1.textContent.trim().length
                        }));
                    }''')
                    
                    h1_count = len(h1_elements)
                    h1_texts = [h1['text'] for h1 in h1_elements if h1['text']]
                    issues = []
                    
                    # Analyze H1 tags
                    if h1_count == 0:
                        issues.append("No H1 tag found")
                    elif h1_count > 1:
                        issues.append(f"Multiple H1 tags found ({h1_count})")
                    
                    for h1 in h1_elements:
                        if h1['text']:
                            if h1['length'] > 70:
                                issues.append(f"H1 too long ({h1['length']} chars): '{h1['text'][:50]}...'")
                            if h1['length'] < 20:
                                issues.append(f"H1 too short ({h1['length']} chars): '{h1['text']}'")
                        else:
                            issues.append("Empty H1 tag text")
                    
                    # Save result to database
                    result = models.H1AuditResult(
                        session_id=session_id,
                        url=url,
                        h1_count=h1_count,
                        h1_texts=json.dumps(h1_texts),
                        issues=json.dumps(issues)
                    )
                    db.add(result)
                    
                    # Update progress
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                        db.commit()
                    
                    print(f"[H1 AUDIT] {url} - {h1_count} H1 tag(s)")
                    
                except Exception as e:
                    print(f"[H1 AUDIT] FAILED {url}: {e}")
                    # Save error result
                    result = models.H1AuditResult(
                        session_id=session_id,
                        url=url,
                        h1_count=0,
                        h1_texts=json.dumps([]),
                        issues=json.dumps([f"Error: {str(e)[:100]}"])
                    )
                    db.add(result)
                    
                    # Update progress even on error
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                        db.commit()
            
            await context.close()
            await browser.close()
            
        # Mark as completed
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"H1 audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    print(f"H1 AUDIT SESSION {session_id} COMPLETED")

# ========== PHONE NUMBER AUDIT FUNCTIONS ==========

async def audit_phone_numbers(urls: List[str], target_numbers: List[str], options: List[str], 
                              session_id: str, user_id: int, db: Session):
    """Audit phone numbers on multiple URLs"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            # Define regex patterns for different countries
            country_patterns = {
                "US": [r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}'],
                "UK": [r'\+44\s?\d{4}\s?\d{6}', r'0\d{4}\s?\d{6}', r'\(0\d{4}\)\s?\d{6}'],
                "CA": [r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'],
                "AU": [r'\+61\s?\d\s?\d{4}\s?\d{4}', r'0\d\s?\d{4}\s?\d{4}'],
                "DE": [r'\+49\s?\d{5,15}', r'0\d{5,15}'],
                "FR": [r'\+33\s?\d{9}', r'0\d{9}'],
                "JP": [r'\+81\s?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{4}'],
                "IN": [r'\+91\s?\d{5}\s?\d{5}', r'0\d{5}\s?\d{5}']
            }
            
            for i, url in enumerate(urls):
                try:
                    # Check if task was stopped
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped":
                        break
                    
                    await page.goto(url, wait_until="networkidle", timeout=90000)
                    await asyncio.sleep(2)  # Wait for page to load
                    
                    # Extract phone numbers with location context
                    found_numbers = await page.evaluate(r'''(patterns) => {
                        const results = [];
                        
                        function getTextNodes(node) {
                            const textNodes = [];
                            if (node.nodeType === 3) {
                                textNodes.push(node);
                            } else {
                                const children = node.childNodes;
                                for (let i = 0; i < children.length; i++) {
                                    textNodes.push(...getTextNodes(children[i]));
                                }
                            }
                            return textNodes;
                        }

                        function getLocation(node) {
                            let current = node;
                            while (current && current.nodeType === 1) { // Element node
                                const tagName = current.tagName.toLowerCase();
                                if (tagName === 'header') return 'Header';
                                if (tagName === 'footer') return 'Footer';
                                current = current.parentElement;
                            }
                            // Check ancestors
                            current = node.parentElement;
                            while (current) {
                                if (current.tagName) {
                                    const tagName = current.tagName.toLowerCase();
                                    if (tagName === 'header') return 'Header';
                                    if (tagName === 'footer') return 'Footer';
                                }
                                current = current.parentElement;
                            }
                            return 'Body';
                        }
                        
                        // Scan all text nodes
                        const body = document.body;
                        const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null, false);
                        
                        let node;
                        while (node = walker.nextNode()) {
                            const text = node.textContent;
                            if (!text || text.trim().length < 5) continue;
                            
                            // Check against all country patterns
                            for (const [country, country_patterns] of Object.entries(patterns)) {
                                for (const pattern of country_patterns) {
                                    // Convert python regex slightly if needed or use simple regex
                                    // For simplicity, we'll send regex strings that work in JS
                                    try {
                                        // Simple approximation for demo: finding numbers
                                        // Real implementation would pass simpler regexes
                                        const regex = new RegExp(pattern.replace(/\(\?<!\\d\)/g, '').replace(/\(?!\d\)/g, ''), 'g'); // Strip lookbehinds if any
                                        
                                        let match;
                                        while ((match = regex.exec(text)) !== null) {
                                            const number = match[0].trim();
                                            const location = getLocation(node);
                                            
                                            // Avoid duplicates in results if possible
                                            const exists = results.find(r => r.number === number);
                                            if (!exists) {
                                                results.push({ number, location, source: 'text' });
                                            }
                                        }
                                    } catch (e) {
                                        // Ignore regex errors
                                    }
                                }
                            }
                        }
                        
                        return results;
                    }''', country_patterns)
                    
                    # Simplify: Playwright JS regex is limited compared to Python's.
                    # APPROACH 2: Hybrid
                    # 1. Get text content of specific regions
                    regions_text = await page.evaluate('''() => {
                        const getRegionText = (selector) => {
                            const els = document.querySelectorAll(selector);
                            let text = "";
                            els.forEach(el => text += " " + el.innerText);
                            return text;
                        };
                        
                        return {
                            header: getRegionText('header'),
                            footer: getRegionText('footer'),
                            body: document.body.innerText
                        };
                    }''')
                    
                    phone_numbers_data = [] # List of dicts: {number, location}
                    seen_numbers = set()
                    issues = []
                    formats_detected = set()
                    
                    # Process regions
                    for region_name, content in regions_text.items():
                        location_label = region_name.capitalize()
                        if not content: continue
                        
                        for number in target_numbers:
                            # Simple substring check (can be improved with strict normalization if needed)
                            if number in content:
                                # Deduplicate globally? or per location? 
                                # Let's deduplicate globally but prefer Header/Footer location if found there
                                if number not in seen_numbers:
                                    seen_numbers.add(number)
                                    phone_numbers_data.append({
                                        "number": number,
                                        "location": location_label if location_label in ["Header", "Footer"] else "Body"
                                    })
                                else:
                                    # If already found in Body but now finding in Header/Footer, update it
                                    if location_label in ["Header", "Footer"]:
                                        for item in phone_numbers_data:
                                            if item["number"] == number and item["location"] == "Body":
                                                item["location"] = location_label
                                                break
                    
                    # Check clickable links (separate check)
                    if "clickable" in options:
                        tel_links = await page.evaluate('''() => {
                            const links = Array.from(document.querySelectorAll('a[href^="tel:"]'));
                            return links.map(link => {
                                // Determine origin
                                let origin = 'Body';
                                if (link.closest('header')) origin = 'Header';
                                if (link.closest('footer')) origin = 'Footer';
                                
                                return {
                                    number: link.href.replace('tel:', '').trim(),
                                    location: origin
                                };
                            });
                        }''')
                        
                        for link in tel_links:
                            p_num = link["number"]
                            p_loc = link["location"]
                            
                            if p_num and p_num not in seen_numbers:
                                seen_numbers.add(p_num)
                                phone_numbers_data.append({
                                    "number": p_num,
                                    "location": p_loc
                                })
                                issues.append("Click-to-call link found")
                            elif p_num:
                                 # Update location if better
                                 if p_loc in ["Header", "Footer"]:
                                     for item in phone_numbers_data:
                                         if item["number"] == p_num and item["location"] == "Body":
                                             item["location"] = p_loc
                                             break

                    # Check schema
                    if "schema" in options:
                         schema_phones = await page.evaluate('''() => {
                            const schemas = Array.from(document.querySelectorAll('[itemtype*="Organization"], [itemtype*="LocalBusiness"]'));
                            const phones = [];
                            schemas.forEach(schema => {
                                const phoneEl = schema.querySelector('[itemprop="telephone"]');
                                if (phoneEl) {
                                    phones.push(phoneEl.textContent.trim());
                                }
                            });
                            return phones;
                        }''')
                         
                         for schema_phone in schema_phones:
                             if schema_phone and schema_phone not in seen_numbers:
                                 seen_numbers.add(schema_phone)
                                 phone_numbers_data.append({
                                     "number": schema_phone,
                                     "location": "Schema"
                                 })
                                 formats_detected.add("schema")

                    # Validate (using stored numbers)
                    if "validate" in options:
                        for item in phone_numbers_data:
                            phone = item["number"]
                            try:
                                parsed = phonenumbers.parse(phone, None)
                                if not phonenumbers.is_valid_number(parsed):
                                    issues.append(f"Invalid phone number format: {phone}")
                            except:
                                issues.append(f"Poorly formatted phone number: {phone}")

                    # Consistency check
                    if "consistency" in options and i > 0:
                        prev_result = db.query(models.PhoneAuditResult).filter_by(
                             session_id=session_id
                        ).order_by(models.PhoneAuditResult.created_at.desc()).first()
                        
                        if prev_result:
                            try:
                                # Prev result might be old string list OR new dict list
                                prev_data = json.loads(prev_result.phone_numbers)
                                prev_numbers_set = set()
                                if prev_data and isinstance(prev_data[0], dict):
                                    prev_numbers_set = {p["number"] for p in prev_data}
                                else:
                                    prev_numbers_set = set(prev_data)
                                    
                                current_numbers_set = {p["number"] for p in phone_numbers_data}
                                
                                if prev_numbers_set != current_numbers_set:
                                    issues.append("Phone numbers differ from other pages")
                            except:
                                pass

                    # Save result
                    result = models.PhoneAuditResult(
                        session_id=session_id,
                        url=url,
                        phone_numbers=json.dumps(phone_numbers_data), # Now storing dicts
                        phone_count=len(phone_numbers_data),
                        formats_detected=json.dumps(list(formats_detected)),
                        issues=json.dumps(issues)
                    )
                    db.add(result)
                    
                    # Update progress
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                        db.commit()
                    
                    print(f"[PHONE AUDIT] {url} - {len(phone_numbers_data)} phone number(s) found")
                    
                except Exception as e:
                    print(f"[PHONE AUDIT] FAILED {url}: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # Save error result
                    result = models.PhoneAuditResult(
                        session_id=session_id,
                        url=url,
                        phone_numbers=json.dumps([]),
                        phone_count=0,
                        formats_detected=json.dumps([]),
                        issues=json.dumps([f"Error: {str(e)[:100]}"])
                    )
                    db.add(result)
                    
                    # Update progress
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                        db.commit()
            
            await context.close()
            await browser.close()
            
        # Mark as completed
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Phone audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    print(f"PHONE AUDIT SESSION {session_id} COMPLETED")

# ========== HELPER FUNCTIONS ==========
def add_browser_frame(img_path: str, url: str):
    """Add browser frame with URL bar to screenshot."""
    try:
        img = Image.open(img_path)
        width, height = img.size
        
        # Create new image with frame
        frame_height = 80
        new_height = height + frame_height
        new_img = Image.new('RGB', (width, new_height), color='white')
        
        # Draw browser frame
        draw = ImageDraw.Draw(new_img)
        
        # Browser top bar
        draw.rectangle([(0, 0), (width, 40)], fill='#f1f3f4')
        
        # Browser controls (circles)
        circle_radius = 6
        circle_spacing = 20
        start_x = 20
        
        colors = ['#ff5f56', '#ffbd2e', '#27ca3f']
        for i, color in enumerate(colors):
            x0 = start_x + i * circle_spacing - circle_radius
            y0 = 20 - circle_radius
            x1 = start_x + i * circle_spacing + circle_radius
            y1 = 20 + circle_radius
            draw.ellipse([(x0, y0), (x1, y1)], fill=color)
        
        # URL bar
        url_bar_height = 30
        url_bar_y = 45
        draw.rectangle([(60, url_bar_y), (width - 20, url_bar_y + url_bar_height)], 
                      fill='#e8eaed', outline='#dadce0', width=1)
        
        # Add URL text (truncate if too long)
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        # Truncate URL if too long
        max_url_width = width - 90
        url_text = url
        bbox = draw.textbbox((0, 0), url_text, font=font)
        text_width = bbox[2] - bbox[0]
        
        if text_width > max_url_width:
            # Truncate with ellipsis
            while text_width > max_url_width and len(url_text) > 10:
                url_text = url_text[:-1]
                bbox = draw.textbbox((0, 0), url_text + "...", font=font)
                text_width = bbox[2] - bbox[0]
            url_text = url_text + "..."
        
        draw.text((70, url_bar_y + 8), url_text, fill='#5f6368', font=font)
        
        # Paste original image below frame
        new_img.paste(img, (0, frame_height))
        
        # Save
        new_img.save(img_path)
        print(f"Added browser frame to: {img_path}")
        
    except Exception as e:
        print(f"Error adding browser frame: {e}")

# ========== BACKGROUND TASKS ==========

def static_audit_task(urls: List[str], browsers: List[str], resolutions: List[str], 
                      session_id: str, user_id: int, session_name: str, access_token: str = None):
    selected_res = [(int(r.split('x')[0]), int(r.split('x')[1])) for r in resolutions]
    
    # Create database session
    db = database.SessionLocal()
    try:
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="static",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps(browsers),
            resolutions=json.dumps(resolutions),
            total_expected=len(urls) * len(browsers) * len(resolutions),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(capture_screenshots(urls, browsers, selected_res, session_id, user_id, db, access_token))
    finally:
        db.close()

def dynamic_audit_task(urls: List[str], browsers: List[str], resolutions: List[str], 
                       session_id: str, user_id: int, session_name: str, access_token: str = None):
    selected_res = [(int(r.split('x')[0]), int(r.split('x')[1])) for r in resolutions]
    
    # Create database session
    db = database.SessionLocal()
    try:
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="dynamic",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps(browsers),
            resolutions=json.dumps(resolutions),
            total_expected=len(urls) * len([b for b in browsers if b in ["Chrome", "Edge"]]) * len(resolutions),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(record_videos_async(urls, browsers, selected_res, session_id, user_id, db, access_token))
    finally:
        db.close()

def h1_audit_task(urls: List[str], session_id: str, user_id: int, session_name: str):
    """Background task for H1 audit"""
    db = database.SessionLocal()
    try:
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="h1",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps([]),
            resolutions=json.dumps([]),
            total_expected=len(urls),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(audit_h1_tags(urls, session_id, user_id, db))
    finally:
        db.close()


async def audit_performance_task(urls: List[str], session_id: str, strategy: str = "desktop"):
    """Background task for Performance audit using Playwright (Threaded/Sync wrapper)"""
    print(f"DEBUG: Starting performance audit task for {session_id}")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _audit_performance_sync, urls, session_id, strategy)

def _audit_performance_sync(urls: List[str], session_id: str, strategy: str):
    print(f"DEBUG: Performance sync thread started for {session_id}")
    from playwright.sync_api import sync_playwright
    
    db = database.SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            completed_count = 0
            for url in urls:
                # Refresh session
                db.expire_all()
                session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                if not session or session.status == "stopped":
                    break
                    
                try:
                    if strategy == "mobile":
                        # iPhone 12
                        device = p.devices['iPhone 12']
                        context = browser.new_context(**device)
                    else:
                        context = browser.new_context()

                    page = context.new_page()
                    try:
                        # Navigate
                        page.goto(url, wait_until="load", timeout=45000)
                        
                        # Get Timing
                        timings_str = page.evaluate("JSON.stringify(window.performance.timing)")
                        timings = json.loads(timings_str)
                        
                        nav_start = timings['navigationStart']
                        ttfb = max(0, timings['responseStart'] - nav_start)
                        dom_load = max(0, timings['domContentLoadedEventEnd'] - nav_start)
                        page_load = max(0, timings['loadEventEnd'] - nav_start)
                        
                        # FCP
                        fcp = 0
                        try:
                            fcp_raw = page.evaluate("""() => {
                                const paint = performance.getEntriesByType('paint').find(e => e.name === 'first-contentful-paint');
                                return paint ? paint.startTime : 0;
                            }""")
                            fcp = int(fcp_raw)
                        except: pass
                        
                        # Resources
                        resource_count = page.evaluate("performance.getEntriesByType('resource').length")
                        
                        # Score
                        score = 100
                        if page_load > 3000: score -= 10
                        if page_load > 5000: score -= 20
                        if ttfb > 500: score -= 10
                        if score < 0: score = 0
                        
                        result = models.PerformanceAuditResult(
                            session_id=session_id,
                            url=url,
                            device_preset="Mobile" if strategy == "mobile" else "Desktop",
                            ttfb=ttfb,
                            fcp=fcp,
                            dom_load=dom_load,
                            page_load=page_load,
                            resource_count=resource_count,
                            score=score
                        )
                        db.add(result)
                        db.commit()
                        
                    finally:
                        page.close()
                        context.close()
                        
                except Exception as e:
                    print(f"Perf Error {url}: {e}")
                    # Log error in DB?
                    result = models.PerformanceAuditResult(
                        session_id=session_id,
                        url=url,
                        score=0
                    )
                    db.add(result)
                    db.commit()

                completed_count += 1
                session.completed = completed_count
                db.commit()

            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            browser.close()
            
    except Exception as e:
        print(f"Performance Audit Fatal Error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()

async def audit_meta_tags_logic(urls: List[str], session_id: str):
    """Background task for Meta Tags audit using raw HTTP + Regex to avoid Playwright overhead/bugs"""
    db = database.SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return

        import httpx
        
        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            completed_count = 0
            for url in urls:
                db.refresh(session)
                if session.status == "stopped": break
                
                try:
                    resp = await client.get(url, timeout=30)
                    html = resp.text
                    
                    # Title
                    title = ""
                    title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
                    if title_match: title = title_match.group(1).strip()
                    
                    # Description
                    description = ""
                    desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
                    if not desc_match:
                        desc_match = re.search(r'<meta[^>]*content=["\'](.*?)["\'][^>]*name=["\']description["\']', html, re.IGNORECASE)
                    if desc_match: description = desc_match.group(1).strip()
                    
                    # Keywords
                    keywords = ""
                    kw_match = re.search(r'<meta[^>]*name=["\']keywords["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
                    if kw_match: keywords = kw_match.group(1).strip()
                    
                    # Canonical
                    canonical = ""
                    canon_match = re.search(r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\'](.*?)["\']', html, re.IGNORECASE)
                    if canon_match: canonical = canon_match.group(1).strip()
                    
                    # OG Tags
                    og_tags = {}
                    og_matches = re.finditer(r'<meta[^>]*property=["\'](og:.*?)["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
                    for m in og_matches:
                        og_tags[m.group(1)] = m.group(2)

                    # Twitter Tags
                    twitter_tags = {}
                    tw_matches = re.finditer(r'<meta[^>]*name=["\'](twitter:.*?)["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
                    for m in tw_matches:
                        twitter_tags[m.group(1)] = m.group(2)
                    
                    # Schema
                    schema_tags = []
                    schema_matches = re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL)
                    for m in schema_matches:
                        try:
                            schema_tags.append(json.loads(m.group(1)))
                        except:
                            pass
                    
                    # --- Rich Analysis ---
                    
                    # Keyword Consistency
                    from collections import Counter
                    def tokenize(text):
                        if not text: return []
                        # Simple regex tokenizer for 3+ letter words
                        return [w.lower() for w in re.findall(r'[a-zA-Z]{3,}', text)]
                    
                    # Extract visible text (simple regex approximation)
                    # Remove scripts, styles, html tags
                    body_text = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                    body_text = re.sub(r'<style.*?</style>', '', body_text, flags=re.DOTALL | re.IGNORECASE)
                    body_text = re.sub(r'<[^>]+>', ' ', body_text)
                    
                    body_tokens = tokenize(body_text)
                    body_counts = Counter(body_tokens)
                    
                    target_keywords = tokenize(title + " " + keywords + " " + description)
                    target_keywords = list(set(target_keywords))
                    
                    keyword_consistency = {}
                    for kw in target_keywords:
                        keyword_consistency[kw] = body_counts.get(kw, 0)
                        
                    # Validation
                    warnings = []
                    missing_tags = []
                    score = 100
                    
                    # Title Checks
                    if not title:
                        missing_tags.append("Title")
                        score -= 20
                    elif len(title) < 30:
                        warnings.append(f"Title is too short ({len(title)} chars). Recommended: 30-60 chars.")
                        score -= 5
                    elif len(title) > 60:
                        warnings.append(f"Title is too long ({len(title)} chars). Recommended: < 60 chars.")
                        score -= 5
                        
                    # Description Checks
                    if not description:
                        missing_tags.append("Description")
                        score -= 20
                    elif len(description) < 70:
                        warnings.append(f"Description is too short ({len(description)} chars). Recommended: 70-155 chars.")
                        score -= 5
                    elif len(description) > 155:
                        warnings.append(f"Description is too long ({len(description)} chars). Recommended: < 155 chars.")
                        score -= 5
                        
                    # Canonical Check
                    if not canonical:
                        warnings.append("Missing Canonical URL.")
                        score -= 10
                        
                    # OG Check
                    if not og_tags:
                        warnings.append("Missing Open Graph tags.")
                        score -= 10
                        
                    if score < 0: score = 0
                    
                    result = models.MetaTagsResult(
                        session_id=session_id,
                        url=url,
                        title=title,
                        description=description,
                        keywords=keywords,
                        canonical=canonical,
                        og_tags=json.dumps(og_tags),
                        twitter_tags=json.dumps(twitter_tags),
                        schema_tags=json.dumps(schema_tags),
                        missing_tags=json.dumps(missing_tags),
                        warnings=json.dumps(warnings),
                        keyword_consistency=json.dumps(keyword_consistency),
                        score=score
                    )
                    db.add(result)
                    db.commit()
                    
                except Exception as e:
                    print(f"Meta audit failed for {url}: {e}")
                
                completed_count += 1
                session.completed = completed_count
                db.commit()

            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        print(f"Meta tags audit failed: {e}")
        session.status = "error"
        db.commit()
    finally:
        db.close()

async def audit_sitemap_logic(url: str, session_id: str):
    """Background task for Sitemap audit"""
    db = database.SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return

        # Fetch sitemap
        import xml.etree.ElementTree as ET
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, timeout=30)
                # Remove namespaces for easier parsing in simple logic
                xml_content = re.sub(r' xmlns="[^"]+"', '', resp.text, count=1)
                root = ET.fromstring(xml_content)
                
                # Count URLs
                # Handle standard sitemap (urlset/url) or sitemap index (sitemapindex/sitemap)
                tag = root.tag
                if 'sitemapindex' in tag:
                    is_index = True
                    children = [child.findtext('loc') for child in root.findall('sitemap')]
                    count = len(children)
                else:
                    is_index = False
                    urls = root.findall('url')
                    count = len(urls)
                    children = []
                
                # Check robots.txt (simple assumptions)
                domain_match = re.search(r'(https?://[^/]+)', url)
                domain = domain_match.group(1) if domain_match else ""
                robots_url = f"{domain}/robots.txt"
                
                robots_status = "unknown"
                if domain:
                    try:
                        robots_resp = await client.get(robots_url, timeout=10)
                        if robots_resp.status_code == 200:
                             robots_status = "found" if "Sitemap:" in robots_resp.text else "found_no_link"
                        else:
                             robots_status = "missing"
                    except:
                        robots_status = "error"
                
                result = models.SitemapResult(
                    session_id=session_id,
                    url=url,
                    is_index=is_index,
                    url_count=count,
                    child_sitemaps=json.dumps(children) if children else "[]",
                    robots_status=robots_status,
                    load_time_ms=int(resp.elapsed.total_seconds() * 1000),
                    score=90 if robots_status == "found" else 70 
                )
                db.add(result)
                session.completed = 1
                session.status = "completed"
                db.commit()
                
            except Exception as e:
                print(f"Sitemap fetch error: {e}")
                session.status = "error"
                db.commit()
                
    except Exception as e:
        print(f"Sitemap task error: {e}")
        session.status = "error"
        db.commit()
    finally:
        db.close()


async def audit_accessibility_task(urls: List[str], session_id: str):
    """Background task for Accessibility audit (Threaded/Sync wrapper)"""
    print(f"DEBUG: Starting accessibility audit task for {session_id}")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _audit_accessibility_sync, urls, session_id)

def _audit_accessibility_sync(urls: List[str], session_id: str):
    print(f"DEBUG: Accessibility sync thread started for {session_id}")
    from playwright.sync_api import sync_playwright
    import requests # Use requests for simple sync fetch, or httpx.Client
    import httpx
    
    db = database.SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return
        
        # Fetch axe-core synchronously
        axe_source = ""
        try:
            # Using httpx sync client since it is already installed
            with httpx.Client() as client:
                resp = client.get("https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.0/axe.min.js", timeout=10)
                axe_source = resp.text
        except Exception as e:
            print(f"Failed to fetch axe-core: {e}")
            session.status = "error"
            db.commit()
            return
            
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            completed_count = 0
            for url in urls:
                # Refresh session status
                db.expire_all()
                session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                if not session or session.status == "stopped": 
                    break
                
                try:
                    page = browser.new_page()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        
                        # Inject and run axe
                        page.evaluate(axe_source)
                        results = page.evaluate("axe.run()")
                        
                        violations = results.get('violations', [])
                        
                        # Calculate Score
                        critical = sum(1 for v in violations if v.get('impact') == 'critical')
                        serious = sum(1 for v in violations if v.get('impact') == 'serious')
                        moderate = sum(1 for v in violations if v.get('impact') == 'moderate')
                        minor = sum(1 for v in violations if v.get('impact') == 'minor')
                        
                        score = 100 - (critical * 10 + serious * 5 + moderate * 2)
                        if score < 0: score = 0
                        
                        res_entry = models.AccessibilityAuditResult(
                            session_id=session_id,
                            url=url,
                            score=score,
                            violations_count=len(violations),
                            critical_count=critical,
                            serious_count=serious,
                            moderate_count=moderate,
                            minor_count=minor,
                            report_json=json.dumps(violations) 
                        )
                        db.add(res_entry)
                        db.commit()
                        
                    finally:
                        page.close()
                    
                except Exception as e:
                    print(f"A11y error {url}: {e}")
                    # Log error entry?
                    # For now just continue

                completed_count += 1
                session.completed = completed_count
                db.commit()

            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            browser.close()
            
    except Exception as e:
        print(f"Accessibility Audit Fatal Error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()

async def audit_phone_numbers(urls: List[str], target_numbers: List[str], options: List[str], 
                               session_id: str, user_id: int, db: Session):
    """Audit phone numbers - search for specific target numbers on URLs"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            for url in urls:
                try:
                    # Check if session was stopped
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped":
                        break
                    
                    print(f"[PHONE AUDIT] Checking {url}")
                    
                    page = await browser.new_page()
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    
                    # Get page content
                    content = await page.content()
                    text_content = await page.inner_text('body')
                    
                    # Search for each target number
                    numbers_found = []
                    issues = []
                    
                    for target_number in target_numbers:
                        # Clean the target number for searching (remove spaces, dashes, etc.)
                        clean_target = ''.join(filter(str.isdigit, target_number))
                        
                        # Count occurrences in text content
                        count = text_content.count(target_number)
                        
                        # Also search for variations (with/without formatting)
                        if count == 0:
                            # Try without formatting
                            count = text_content.count(clean_target)
                        
                        if count > 0:
                            numbers_found.append({
                                'number': target_number,
                                'count': count
                            })
                            print(f"  Found: {target_number} ({count} times)")
                        else:
                            print(f"  Not found: {target_number}")
                    
                    # Check for issues based on options
                    if 'validate_formats' in options:
                        # Check if numbers are in valid formats
                        for num_data in numbers_found:
                            num = num_data['number']
                            if not any(char in num for char in ['-', ' ', '(', ')']):
                                issues.append(f"Number {num} has no formatting")
                    
                    if 'check_links' in options:
                        # Check if numbers are clickable links
                        for num_data in numbers_found:
                            num = num_data['number']
                            clean_num = ''.join(filter(str.isdigit, num))
                            tel_link = f'tel:{clean_num}'
                            if tel_link not in content and f'tel:+{clean_num}' not in content:
                                issues.append(f"Click-to-call link not found for {num}")
                    
                    if 'check_schema' in options:
                        # Check for schema markup
                        if 'telephone' not in content.lower():
                            issues.append("No telephone schema markup found")
                    
                    # Determine status
                    if len(numbers_found) == 0:
                        status = "Not Found"
                    elif len(numbers_found) == len(target_numbers):
                        status = "All Found"
                    else:
                        status = "Partial"
                    
                    # Create result record
                    result = models.PhoneAuditResult(
                        session_id=session_id,
                        url=url,
                        phone_count=len(numbers_found),
                        phone_numbers=json.dumps(numbers_found),
                        formats_detected=json.dumps([]),  # Empty for now, can be enhanced later
                        issues=json.dumps(issues)
                    )
                    db.add(result)
                    
                    # Update session progress
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                    db.commit()
                    
                    await page.close()
                    
                except Exception as e:
                    print(f"Error auditing {url}: {e}")
                    # Save error result
                    result = models.PhoneAuditResult(
                        session_id=session_id,
                        url=url,
                        phone_count=0,
                        phone_numbers=json.dumps([]),
                        formats_detected=json.dumps([]),
                        issues=json.dumps([f"Error: {str(e)}"])
                    )
                    db.add(result)
                    db.commit()
            
            await browser.close()
            
            # Mark session as completed
            session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
            if session:
                session.status = "completed"
                session.completed_at = datetime.utcnow()
                db.commit()
            
            print(f"PHONE AUDIT SESSION {session_id} COMPLETED")
            
    except Exception as e:
        print(f"Phone Audit Fatal Error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()

def phone_audit_task(urls: List[str], target_numbers: List[str], options: List[str], 
                     session_id: str, user_id: int, session_name: str):
    """Background task for phone audit"""
    db = database.SessionLocal()
    try:
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="phone",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps([]),
            resolutions=json.dumps([]),
            total_expected=len(urls),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(audit_phone_numbers(urls, target_numbers, options, session_id, user_id, db))
    finally:
        db.close()

# ========== ROUTES ==========

@app.get("/")
async def home(request: Request, db: Session = Depends(auth.get_db)):
    """Root route - Landing page for guests, redirect to Dashboard for users"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        # Redirect to new SaaS Dashboard if authenticated
        return RedirectResponse(url="/platform/dashboard", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    
    # Show Marketing Landing Page if not authenticated
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": None
    })

@app.get("/dashboard")
async def dashboard(request: Request, user = Depends(require_auth)):
    """Dashboard route - requires authentication"""
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": user,
        "show_nav": True
    })

@app.get("/login")
async def login_page(request: Request, db: Session = Depends(auth.get_db)):
    """Login page - redirects to dashboard if already logged in"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return templates.TemplateResponse("login.html", {
        "request": request, 
        "google_client_id": settings.google_client_id
    })

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response

@app.get("/register")
async def register_page(request: Request, db: Session = Depends(auth.get_db)):
    """Register page - redirects to dashboard if already logged in"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return templates.TemplateResponse("register.html", {
        "request": request,
        "google_client_id": settings.google_client_id
    })

@app.get("/reset-password")
async def reset_password_page(request: Request):
    """Reset Password Page"""
    return templates.TemplateResponse("reset-password.html", {"request": request})

@app.get("/forgot-password")
async def forgot_password_redirect():
    """Redirect legacy forgot password link to reset password page"""
    return RedirectResponse(url="/reset-password")

@app.get("/platform/history")
async def history_page(request: Request, db: Session = Depends(auth.get_db)):
    """History page - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    # Get user's sessions
    sessions = db.query(models.AuditSession).filter_by(user_id=user.id).order_by(models.AuditSession.created_at.desc()).all()
    
    # Parse JSON strings
    for session in sessions:
        try:
            session.urls = json.loads(session.urls)
        except:
            session.urls = []
    
    # Calculate stats
    total_sessions = len(sessions)
    completed_sessions = len([s for s in sessions if s.status == "completed"])
    running_sessions = len([s for s in sessions if s.status == "running"])
    static_sessions = len([s for s in sessions if s.session_type == "static"])
    dynamic_sessions = len([s for s in sessions if s.session_type == "dynamic"])
    h1_sessions = len([s for s in sessions if s.session_type == "h1"])
    phone_sessions = len([s for s in sessions if s.session_type == "phone"])
    
    # Pre-calculate progress for each session
    for session in sessions:
        if session.total_expected > 0:
            session.progress_percent = round((session.completed / session.total_expected) * 100, 1)
        else:
            session.progress_percent = 0

    return templates.TemplateResponse("history.html", {
        "request": request, 
        "user": user,
        "sessions": sessions
    })

@app.get("/platform/profile")
async def profile_page(request: Request, db: Session = Depends(auth.get_db)):
    """Profile page - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    # Fetch user stats
    total_sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).count()
    completed_audits = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id, models.AuditSession.status == "completed").count()

    stats = {
        "total_sessions": total_sessions,
        "completed_audits": completed_audits,
        "success_rate": int((completed_audits / total_sessions * 100)) if total_sessions > 0 else 0
    }

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "stats": stats
    })
        
@app.get("/responsive")
async def responsive_page(request: Request, user = Depends(require_auth)):
    """Responsive audit page - requires authentication"""
    return templates.TemplateResponse("responsive.html", {"request": request, "user": user})

@app.get("/responsive/static")
async def static_audit_page(request: Request, user = Depends(require_auth)):
    """Static audit page - requires authentication"""
    return templates.TemplateResponse("static-audit.html", {"request": request, "user": user})

@app.get("/static-results/{session_id}")
async def static_results_view(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """View static audit results - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Parse JSON fields
    try:
        session.urls = json.loads(session.urls)
        session.browsers = json.loads(session.browsers)
        session.resolutions = json.loads(session.resolutions)
    except:
        pass
        
    # Get results from DB
    results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
    
    # Serialize results for JS
    results_list = []
    for r in results:
        results_list.append({
            "url": r.url,
            "browser": r.browser,
            "resolution": r.resolution,
            "filename": r.filename,
            "screenshot_path": r.screenshot_path # Include full path/URL
        })
    
    import time
    cache_buster = int(time.time())  # Add timestamp to force cache invalidation
    
    return templates.TemplateResponse("static-results.html", {
        "request": request,
        "user": user,
        "session": session,
        "results": results,
        "results_data": json.dumps(results_list),
        "results_json": json.dumps([r.url for r in results]),
        "cache_buster": cache_buster  # Force browser to reload template
    })


@app.get("/dynamic-results/{session_id}")
async def dynamic_results_view(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """View dynamic audit results - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Parse JSON fields
    try:
        if isinstance(session.urls, str):
            session.urls = json.loads(session.urls)
    except:
        session.urls = []

    try:
        if isinstance(session.browsers, str):
            session.browsers = json.loads(session.browsers)
    except:
        session.browsers = []

    try:
        if isinstance(session.resolutions, str):
            session.resolutions = json.loads(session.resolutions)
    except:
        session.resolutions = []

    # Get results from DB
    results = db.query(models.DynamicAuditResult).filter_by(session_id=session_id).all()
    
    # Serialize results for JS
    results_list = []
    for r in results:
        results_list.append({
            "url": r.url,
            "browser": r.browser,
            "resolution": r.resolution,
            "video_path": r.video_path,
            "filename": r.filename
        })

    return templates.TemplateResponse("dynamic-results.html", {
        "request": request,
        "user": user,
        "session": session,
        "results": results, # Keep for backward compatibility if needed, though we use results_json now
        "results_json": json.dumps(results_list), 
    })

@app.get("/responsive/dynamic")
async def dynamic_audit_page(request: Request, user = Depends(require_auth)):
    """Dynamic audit page - requires authentication"""
    return templates.TemplateResponse("dynamic-audit.html", {"request": request, "user": user})

@app.get("/h1-audit")
async def h1_audit_page(request: Request, user = Depends(require_auth)):
    """H1 audit page - requires authentication"""
    return templates.TemplateResponse("h1-audit.html", {"request": request, "user": user})

@app.get("/phone-audit")
async def phone_audit_page(request: Request, user = Depends(require_auth)):
    """Phone audit page - requires authentication"""
    return templates.TemplateResponse("phone-audit.html", {"request": request, "user": user})

@app.get("/platform/visual")
async def visual_page(request: Request, user = Depends(require_auth)):
    """Visual audit page - requires authentication"""
    return templates.TemplateResponse("visual_regression.html", {"request": request, "user": user})

# ========== API ROUTES ==========

@app.post("/api/auth/register")
async def register(
    request: RegisterRequest, 
    db: Session = Depends(auth.get_db)
):
    """Register new user using Supabase Auth"""
    try:
        # Check if username exists locally first (optional optimization)
        if db.query(models.User).filter(models.User.username == request.username).first():
            raise HTTPException(status_code=400, detail="Username already taken")

        # Register locally
        user = auth.register_user(request.email, request.password, request.username, db)

        print(f"User created successfully: {user.id}, {user.username}")

        # Auto-login to get token
        login_data = auth.login_user(request.email, request.password, db)

        return {
            "access_token": login_data["access_token"],
            "token_type": "bearer",
            "user": {"id": user.id, "username": user.username}
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Registration error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.post("/api/auth/login")
async def login(
    request: LoginRequest,
    db: Session = Depends(auth.get_db)
):
    """Login user and return access token with HttpOnly cookie"""
    print(f"Login attempt: {request.username}")
    
    try:
        if request.email:
            # Strict mode: Check if email exists
            user = db.query(models.User).filter(models.User.email == request.email).first()
            if not user:
                 raise HTTPException(status_code=400, detail="Incorrect email or password")
            
            # Verify username matches
            if user.username != request.username:
                 raise HTTPException(status_code=400, detail="Username does not match email")
            
            email = request.email
        else:
            # Fallback (though frontend should send both)
            email = request.username
            if "@" not in email:
                user = db.query(models.User).filter(models.User.username == request.username).first()
                if not user:
                     raise HTTPException(status_code=400, detail="Incorrect username or password")
                email = user.email

        # Authenticate locally
        login_data = auth.login_user(email, request.password, db)
        
        user = login_data["user"]
        
        # Create response with HttpOnly cookie (matching Google login)
        response = JSONResponse({
            "access_token": login_data["access_token"], 
            "token_type": "bearer", 
            "user": {"id": user.id, "username": user.username}
        })
        
        # Set HttpOnly cookie
        response.set_cookie(
            key="access_token",
            value=login_data["access_token"],
            httponly=True,
            max_age=settings.access_token_expire_minutes * 60,
            samesite="lax",
            secure=False  # Set to True in production with HTTPS
        )
        
        return response
        
    except Exception as e:
        print(f"Login error: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail="Incorrect username or password")

@app.post("/api/auth/google")
async def google_login(request: GoogleLoginRequest, db: Session = Depends(auth.get_db)):
    """Handle Google Login: Verify token, create/get user, issue local token"""
    try:
        # Verify Google Token
        id_info = id_token.verify_oauth2_token(
            request.token, 
            google_requests.Request(), 
            settings.google_client_id
        )
        
        email = id_info.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Google token missing email")
            
        # Check if user exists
        user = db.query(models.User).filter(models.User.email == email).first()
        
        if not user:
            # Register new user automatically
            username = email.split("@")[0]
            # Ensure unique username
            base_username = username
            counter = 1
            while db.query(models.User).filter(models.User.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1
            
            # Create random password (user relies on Google Auth)
            random_password = str(uuid.uuid4())
            user = auth.register_user(email, random_password, username, db)
            print(f"Registered new Google user: {user.username}")
        
        # Create local access token
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = auth.create_access_token(
            data={"sub": user.id, "email": user.email},
            expires_delta=access_token_expires
        )
        
        # Set cookie
        response = JSONResponse({
            "access_token": access_token, 
            "token_type": "bearer",
            "user": {"id": user.id, "username": user.username}
        })
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=settings.access_token_expire_minutes * 60,
            samesite="lax",
            secure=False # Set to True in production with HTTPS
        )
        return response

    except ValueError as e:
        # Invalid token
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")
    except Exception as e:
        print(f"Google Login Error: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")

@app.post("/api/auth/logout")
async def logout():
    """Logout user by clearing cookie"""
    response = JSONResponse({"message": "Logged out successfully"})
    response.delete_cookie(key="access_token")
    return response

# ========== PASSWORD RESET MODELS ==========

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

# ========== PASSWORD RESET ENDPOINTS ==========

@app.get("/forgot-password")
async def forgot_password_page(request: Request):
    """Render forgot password page"""
    return templates.TemplateResponse("forgot-password.html", {"request": request})

@app.post("/api/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(auth.get_db)):
    """Generate password reset token"""
    # Find user by email
    user = db.query(models.User).filter(models.User.email == request.email).first()
    
    if not user:
        # Don't reveal if email exists for security
        return JSONResponse({
            "message": "If the email exists, a reset link has been sent.",
            "reset_link": None
        })
    
    # Generate unique token
    import secrets
    token = secrets.token_urlsafe(32)
    
    # Set expiration (30 minutes from now)
    expires_at = datetime.utcnow() + timedelta(minutes=30)
    
    # Create reset token record
    reset_token = models.PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=expires_at
    )
    db.add(reset_token)
    db.commit()
    
    # For development: return the reset link
    reset_link = f"http://127.0.0.1:8000/reset-password/{token}"
    
    return JSONResponse({
        "message": "Password reset link generated successfully!",
        "reset_link": reset_link  # In production, this would be sent via email
    })

@app.get("/reset-password/{token}")
async def reset_password_page(token: str, request: Request, db: Session = Depends(auth.get_db)):
    """Render reset password page with token validation"""
    # Validate token exists and is not expired
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == token,
        models.PasswordResetToken.used == False,
        models.PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        # Token invalid, expired, or already used
        return templates.TemplateResponse("reset-password.html", {
            "request": request,
            "token": token,
            "error": "Invalid or expired reset token"
        })
    
    return templates.TemplateResponse("reset-password.html", {
        "request": request,
        "token": token
    })

@app.post("/api/auth/reset-password")
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(auth.get_db)):
    """Reset user password with valid token"""
    # Validate token
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == request.token,
        models.PasswordResetToken.used == False,
        models.PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Validate password
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    # Get user
    user = db.query(models.User).filter(models.User.id == reset_token.user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update password locally
    user = db.query(models.User).filter(models.User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    user.hashed_password = auth.get_password_hash(request.password)
    
    # Mark token as used
    reset_token.used = True
    db.commit()
    
    return JSONResponse({
        "message": "Password reset successfully. Please login with your new password."
    })

# Helper function for session cleanup (moved before route definition)
def perform_session_cleanup(session_id: str, db: Session):
    """Helper to cleanup session artifacts and DB records (Child records only)"""
    try:
        # Manual Cascade Delete
        db.query(models.StaticAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.DynamicAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.UnifiedAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.VisualAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.H1AuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.PhoneAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
    except Exception as e:
        print(f"Cleanup Error DB {session_id}: {e}")
        # Ensure we don't rollback here, allow caller to handle transaction
        # But querying and deleting in same transaction reference is fine.

    # Clean up Files (Best effort)
    folders = [
        f"screenshots/{session_id}",
        f"videos/{session_id}",
        f"diffs/{session_id}"
    ]
    for folder in folders:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
            except Exception as e:
                print(f"Error deleting folder {folder}: {e}")

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Delete audit session and associated data"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
         raise HTTPException(status_code=401, detail="Not authenticated")
         
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    try:
        perform_session_cleanup(session_id, db)
        
        # Delete Session
        db.delete(session)
        db.commit()
        
        return JSONResponse({"message": "Session deleted"})
        
    except Exception as e:
        db.rollback()
        print(f"Delete Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")

@app.delete("/api/sessions")
async def clear_all_sessions(request: Request, db: Session = Depends(auth.get_db)):
    """Delete ALL audit sessions for the user"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
         raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get all sessions
    sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).all()
    count = len(sessions)
    deleted = 0
    
    for session in sessions:
        try:
            perform_session_cleanup(session.session_id, db)
            db.delete(session)
            db.commit()
            deleted += 1
        except Exception as e:
            db.rollback()
            print(f"Failed to clear session {session.session_id}: {e}")
            
    return JSONResponse({"message": f"History cleared. Deleted {deleted}/{count} sessions."})

@app.post("/upload/static")
async def upload_static(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    browsers: str = Form(...),
    resolutions: str = Form(...),
    session_name: str = Form("My Static Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for static audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])

    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    selected_browsers = json.loads(browsers)
    selected_resolutions = json.loads(resolutions)

    if not selected_browsers or not selected_resolutions:
        return JSONResponse({"error": "Select at least one browser and resolution"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_expected = len(urls) * len(selected_browsers) * len(selected_resolutions)
    
    token = request.cookies.get("access_token")

    # Start background task
    background_tasks.add_task(static_audit_task, urls, selected_browsers, selected_resolutions, session_id, user.id, session_name, token)
    
    # Store task reference
    running_tasks[session_id] = "static"

    return JSONResponse({
        "session": session_id,
        "total_expected": total_expected,
        "type": "static"
    })

@app.post("/upload/dynamic")
async def upload_dynamic(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    browsers: str = Form(...),
    resolutions: str = Form(...),
    session_name: str = Form("My Dynamic Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for dynamic audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])

    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    selected_browsers = json.loads(browsers)
    selected_resolutions = json.loads(resolutions)

    supported_browsers = [b for b in selected_browsers if b in ["Chrome", "Edge"]]
    if not supported_browsers:
        return JSONResponse({"error": "Select Chrome or Edge for video recording"}, status_code=400)

    if not selected_resolutions:
        return JSONResponse({"error": "Select at least one resolution"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_expected = len(urls) * len(supported_browsers) * len(selected_resolutions)
    
    token = request.cookies.get("access_token")

    # Start background task
    background_tasks.add_task(dynamic_audit_task, urls, supported_browsers, selected_resolutions, session_id, user.id, session_name, token)
    
    # Store task reference
    running_tasks[session_id] = "dynamic"

    return JSONResponse({
        "session": session_id,
        "total_expected": total_expected,
        "type": "dynamic"
    })

@app.post("/upload/h1")
async def upload_h1(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    session_name: str = Form("My H1 Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for H1 audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
        
    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Start background task
    background_tasks.add_task(h1_audit_task, urls, session_id, user.id, session_name)
    
    # Store task reference
    running_tasks[session_id] = "h1"

    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "h1"
    })

@app.post("/upload/phone")
async def upload_phone(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    target_numbers: str = Form(...),
    options: str = Form("[]"),
    session_name: str = Form("My Phone Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for phone audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])

    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    target_numbers_list = [n.strip() for n in target_numbers.splitlines() if n.strip()]
    if not target_numbers_list:
        return JSONResponse({"error": "No target numbers provided"}, status_code=400)

    selected_options = json.loads(options)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Start background task
    background_tasks.add_task(phone_audit_task, urls, target_numbers_list, selected_options, session_id, user.id, session_name)
    
    # Store task reference
    running_tasks[session_id] = "phone"

    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "phone"
    })

@app.post("/api/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Stop a running session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Find session
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update status
    session.status = "stopped"
    db.commit()
    
    return {"message": "Session stopped successfully"}

@app.delete("/api/sessions/{session_id}")
async def delete_session(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Delete a session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Find session
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Delete files
    if session.session_type == "static":
        folder_path = f"screenshots/{session_id}"
    elif session.session_type == "dynamic":
        folder_path = f"videos/{session_id}"
    elif session.session_type == "h1":
        folder_path = f"h1-audits/{session_id}"
    else:
        folder_path = f"phone-audits/{session_id}"
    
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path, ignore_errors=True)
    
    # Delete related audit results
    if session.session_type == "h1":
        results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
        for result in results:
            db.delete(result)
    elif session.session_type == "phone":
        results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
        for result in results:
            db.delete(result)
    
    # Delete database record
    db.delete(session)
    db.commit()
    
    return {"message": "Session deleted successfully"}

@app.delete("/api/sessions")
async def delete_all_sessions(
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Delete all completed sessions for user"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    sessions = db.query(models.AuditSession).filter(
        models.AuditSession.user_id == user.id,
        models.AuditSession.status == "completed"
    ).all()
    
    deleted_count = 0
    for session in sessions:
        # Delete files
        if session.session_type == "static":
            folder_path = f"screenshots/{session.session_id}"
        elif session.session_type == "dynamic":
            folder_path = f"videos/{session.session_id}"
        elif session.session_type == "h1":
            folder_path = f"h1-audits/{session.session_id}"
        else:
            folder_path = f"phone-audits/{session.session_id}"
        
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path, ignore_errors=True)
            
        # Delete related results
        if session.session_type == "h1":
            try:
                db.query(models.H1AuditResult).filter_by(session_id=session.session_id).delete()
            except: pass
        elif session.session_type == "phone":
             try:
                db.query(models.PhoneAuditResult).filter_by(session_id=session.session_id).delete()
             except: pass
        elif session.session_type == "unified":
             try:
                db.query(models.UnifiedAuditResult).filter_by(session_id=session.session_id).delete()
             except: pass
        elif session.session_type == "accessibility":
             try:
                db.query(models.AccessibilityAuditResult).filter_by(session_id=session.session_id).delete()
             except: pass

        db.delete(session)
        deleted_count += 1
        
    db.commit()
    return {"message": f"Deleted {deleted_count} sessions"}

@app.get("/progress/{session_type}/{session_id}")
async def progress(session_type: str, session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/static/{session_id}")
async def static_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a static session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/dynamic/{session_id}")
async def dynamic_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a dynamic session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/h1/{session_id}")
async def h1_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a H1 audit session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/phone/{session_id}")
async def phone_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a phone audit session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/results/{session_type}/{session_id}")
async def view_results(session_type: str, session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """View results of a completed session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    # Verify ownership
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Check if session is completed
    if session.status != "completed":
        raise HTTPException(status_code=400, detail="Session not completed yet")
    
    # Parse session data
    try:
        session.urls = json.loads(session.urls)
        session.browsers = json.loads(session.browsers)
        session.resolutions = json.loads(session.resolutions)
    except:
        session.urls = []
        session.browsers = []
        session.resolutions = []
    
    # Render appropriate results template
    if session_type == "static":
        return templates.TemplateResponse("static-results.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "static"
        })
    elif session_type == "dynamic":
        # Filter browsers to only include Chrome and Edge for dynamic audits
        session.browsers = [b for b in session.browsers if b in ["Chrome", "Edge"]]
        return templates.TemplateResponse("dynamic-results.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "dynamic"
        })
    elif session_type == "h1":
        # Get H1 audit results
        h1_results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
        
        # Convert results to dict format
        results_data = []
        for result in h1_results:
            results_data.append({
                "url": result.url,
                "h1_count": result.h1_count,
                "h1_texts": result.h1_texts,
                "issues": result.issues
            })
        
        return templates.TemplateResponse("h1-results.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "h1",
            "results": results_data
        })
    elif session_type == "phone":
        return RedirectResponse(f"/platform/phone-audit?status=completed&session_id={session_id}")
    elif session_type == "performance":
        return RedirectResponse(f"/platform/performance?status=completed&session_id={session_id}")
    elif session_type == "accessibility":
        return RedirectResponse(f"/platform/accessibility?status=completed&session_id={session_id}")
    elif session_type == "meta-tags":
        return RedirectResponse(f"/scan/meta-tags?status=completed&session_id={session_id}")
    elif session_type == "sitemap":
        return RedirectResponse(f"/scan/xml-sitemaps?status=completed&session_id={session_id}")
    else:
        raise HTTPException(status_code=400, detail="Invalid session type")

@app.get("/progress/performance/{session_id}")
async def performance_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a performance audit session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/h1-results/{session_id}")
async def get_h1_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get H1 audit results for a session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Verify ownership
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get results
    results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
    
    # Convert to list of dicts
    results_data = []
    for result in results:
        try:
            h1_texts = json.loads(result.h1_texts) if result.h1_texts else []
            issues = json.loads(result.issues) if result.issues else []
        except:
            h1_texts = []
            issues = []
            
        results_data.append({
            "url": result.url,
            "h1_count": result.h1_count,
            "h1_texts": h1_texts,
            "issues": issues,
            "created_at": result.created_at.isoformat() if result.created_at else None
        })
    
    return JSONResponse(results_data)

@app.get("/phone-results/{session_id}")
async def get_phone_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get phone audit results for a session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Verify ownership
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get results
    results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
    
    # Convert to list of dicts
    results_data = []
    for result in results:
        try:
            phone_numbers = json.loads(result.phone_numbers) if result.phone_numbers else []
            formats_detected = json.loads(result.formats_detected) if result.formats_detected else []
            issues = json.loads(result.issues) if result.issues else []
        except:
            phone_numbers = []
            formats_detected = []
            issues = []
            
        results_data.append({
            "url": result.url,
            "phone_count": result.phone_count,
            "phone_numbers": phone_numbers,
            "formats_detected": formats_detected,
            "issues": issues,
            "created_at": result.created_at.isoformat() if result.created_at else None
        })
    
    return JSONResponse(results_data)

@app.get("/check-files/{session_type}/{session_id}")
async def check_files(session_type: str, session_id: str, browser: str, url: str):
    """Check if files exist for a specific URL and browser"""
    try:
        unique = get_unique_filename(url)
        
        if session_type == "static":
            # Check for screenshots
            files_exist = []
            resolutions = ["1920x1080", "1366x768", "1280x720", "1024x768", "768x1024", "480x800"]
            
            for res in resolutions:
                file_path = f"screenshots/{session_id}/{browser}/{unique}__{res}.png"
                if os.path.exists(file_path):
                    files_exist.append(res)
            
            return {"files_exist": files_exist, "total_checked": len(resolutions)}
        elif session_type == "dynamic":
            # Check for videos
            files_exist = []
            resolutions = ["1920x1080", "1366x768", "1280x720", "1024x768", "768x1024", "480x800"]
            
            for res in resolutions:
                file_path = f"videos/{session_id}/{browser}/{unique}__{res}.mp4"
                if os.path.exists(file_path):
                    files_exist.append(res)
            
            return {"files_exist": files_exist, "total_checked": len(resolutions)}
        else:
            return {"files_exist": [], "total_checked": 0}
    except Exception as e:
        return {"error": str(e), "files_exist": [], "total_checked": 0}

# ========== STREAMING RESPONSE FOR VIDEOS ==========

@app.get("/videos/{session_id}/{browser}/{video_file}")
async def stream_video(session_id: str, browser: str, video_file: str, request: Request):
    """Stream video files for dynamic results"""
    video_path = f"videos/{session_id}/{browser}/{video_file}"
    
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    
    file_size = os.path.getsize(video_path)
    range_header = request.headers.get("Range")
    
    if range_header:
        # Parse Range header
        start_str, end_str = range_header.replace("bytes=", "").split("-")
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
        
        if start >= file_size:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        
        end = min(end, file_size - 1)
        length = end - start + 1
        
        with open(video_path, "rb") as video:
            video.seek(start)
            data = video.read(length)
        
        response = StreamingResponse(
            iter([data]),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Disposition": f"inline; filename={video_file}"
            }
        )
        return response
    else:
        # Return full file
        file_like = open(video_path, mode="rb")
        return StreamingResponse(
            file_like,
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Disposition": f"inline; filename={video_file}"
            }
        )

# ========== VISUAL REGRESSION FUNCTIONS ==========

async def compare_images_logic(base_url: str, compare_url: str, session_id: str, db: Session):
    session_folder = f"diffs/{session_id}"
    os.makedirs(session_folder, exist_ok=True)
    
    extraction_script = """
    () => {
        const elements = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
        while (walker.nextNode()) {
            const node = walker.currentNode;
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            
            if (rect.width === 0 || rect.height === 0 || style.display === 'none' || style.visibility === 'hidden') continue;
            
            const hasText = Array.from(node.childNodes).some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim().length > 0);
            
            if (hasText || node.tagName === 'IMG' || node.tagName === 'BUTTON' || node.tagName === 'INPUT') {
                elements.push({
                    tag: node.tagName,
                    id: node.id,
                    classes: [...node.classList],
                    text: node.innerText?.trim().substring(0, 200) || "",
                    rect: {
                        x: rect.x + window.scrollX,
                        y: rect.y + window.scrollY,
                        width: rect.width,
                        height: rect.height
                    },
                    styles: {
                        'color': style.color,
                        'background-color': style.backgroundColor,
                        'font-family': style.fontFamily,
                        'font-size': style.fontSize,
                        'font-weight': style.fontWeight,
                        'text-align': style.textAlign
                    }
                });
            }
        }
        return elements;
    }
    """
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()
            
            # Capture Base
            await page.goto(base_url, wait_until="networkidle", timeout=60000)
            base_path = f"{session_folder}/base.png"
            await page.screenshot(path=base_path, full_page=True)
            base_dom = await page.evaluate(extraction_script)
            
            # Capture Compare
            await page.goto(compare_url, wait_until="networkidle", timeout=60000)
            compare_path = f"{session_folder}/compare.png"
            await page.screenshot(path=compare_path, full_page=True)
            compare_dom = await page.evaluate(extraction_script)
            
            await browser.close()
            
            # Calculate DOM Diff
            try:
                dom_diffs = dom_diff.compare_dom_elements(base_dom, compare_dom)
                with open(f"{session_folder}/diff_report.json", "w") as f:
                    json.dump(dom_diffs, f)
            except Exception as e:
                print(f"DOM Diff Error: {e}")

            # Compare logic (Pixel Diff)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, process_image_diff, base_path, compare_path, session_folder, session_id, base_url, compare_url)

    except Exception as e:
        print(f"Visual Audit Error: {e}")
        pass

def process_image_diff(base_path, compare_path, session_folder, session_id, base_url, compare_url):
    # This runs in a thread
    import database
    from sqlalchemy.orm import Session
    
    # Create new db session for thread
    db = database.SessionLocal()
    
    try:
        img1 = Image.open(base_path).convert("RGB")
        img2 = Image.open(compare_path).convert("RGB")
        
        # Resize to match smallest dimensions to avoid errors
        width = min(img1.width, img2.width)
        height = min(img1.height, img2.height)
        
        img1 = img1.resize((width, height))
        img2 = img2.resize((width, height))
        
        diff_img = Image.new("RGB", (width, height))
        diff_pixels = diff_img.load()
        
        pixels1 = img1.load()
        pixels2 = img2.load()
        
        diff_count = 0
        total_pixels = width * height
        
        for y in range(height):
            for x in range(width):
                r1, g1, b1 = pixels1[x, y]
                r2, g2, b2 = pixels2[x, y]
                
                diff = abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)
                if diff > 15: # Threshold
                    diff_pixels[x, y] = (255, 0, 0) # Highlight Red
                    diff_count += 1
                else:
                    # Fade out slightly
                    diff_pixels[x, y] = (int(r1*0.3), int(g1*0.3), int(b1*0.3))
        
        diff_path = f"{session_folder}/diff.png"
        diff_img.save(diff_path)
        
        diff_score = int((diff_count / total_pixels) * 100)
        
        # Save Result
        result = models.VisualAuditResult(
            session_id=session_id,
            base_url=base_url,
            compare_url=compare_url,
            diff_score=diff_score,
            base_image_path=base_path,
            compare_image_path=compare_path,
            diff_image_path=diff_path
        )
        db.add(result)
        
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed = 1
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Diff processing error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()

# ========== ACCESSIBILITY AUDIT FUNCTIONS ==========




# ========== META TAGS AUDIT FUNCTIONS ==========



# ========== XML SITEMAP AUDIT FUNCTIONS ==========

import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import httpx
import time

async def audit_sitemap_logic(sitemap_url: str, session_id: str):
    db = database.SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return
        
        warnings = []
        errors = []
        
        # --- 1. PERFORMANCE & ROBOTS CHECK ---
        start_time = time.time()
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                # Performance Check
                resp = await client.get(sitemap_url)
                load_time_ms = int((time.time() - start_time) * 1000)
                
                if resp.status_code != 200:
                    raise Exception(f"Sitemap returned status code {resp.status_code}")
                
                # Content-Type Check & Smart Discovery
                ctype = resp.headers.get("content-type", "").lower()
                if "text/html" in ctype:
                    print(f"HTML detected at {sitemap_url}, attempting Auto-Discovery...")
                    
                    found_sitemap = None
                    
                    # 1. Check robots.txt
                    try:
                        parsed = urlparse(sitemap_url)
                        base_url = f"{parsed.scheme}://{parsed.netloc}"
                        robots_resp = await client.get(f"{base_url}/robots.txt", timeout=5.0)
                        if robots_resp.status_code == 200:
                            import re
                            # Find "Sitemap: https://..."
                            sm_match = re.search(r'Sitemap:\s*(https?://[^\s]+)', robots_resp.text, re.IGNORECASE)
                            if sm_match:
                                found_sitemap = sm_match.group(1).strip()
                                print(f"Discovered via robots.txt: {found_sitemap}")
                    except Exception as e:
                        print(f"Robots discovery failed: {e}")

                    # 2. Check common paths if not found
                    if not found_sitemap:
                        common_paths = ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap.txt"]
                        for path in common_paths:
                            try:
                                test_url = f"{base_url}{path}"
                                head_resp = await client.head(test_url, timeout=3.0)
                                if head_resp.status_code == 200:
                                    found_sitemap = test_url
                                    print(f"Discovered common path: {found_sitemap}")
                                    break
                            except: pass
                    
                    # 3. If found, Redirect logic
                    if found_sitemap:
                        sitemap_url = found_sitemap
                        # Refetch with new URL
                        resp = await client.get(sitemap_url)
                        if resp.status_code != 200: raise Exception("Discovered sitemap unreachable.")
                        content = resp.content
                        warnings.append(f"Automatically discovered sitemap at: {found_sitemap}")
                    
                    # 4. Fallback: Virtual Sitemap (Crawl the page)
                    else:
                        print("No sitemap found. Generating Virtual Sitemap from homepage links...")
                        import re
                        page_content = resp.text
                        # Extract all hrefs
                        links = re.findall(r'<a\s+(?:[^>]*?\s+)?href=["\'](.*?)["\']', page_content, re.IGNORECASE)
                        
                        # Filter internal links
                        unique_links = set()
                        base_domain = parsed.netloc
                        
                        for link in links:
                            link = link.strip()
                            if not link or link.startswith('#') or link.startswith('mailto:') or link.startswith('tel:'):
                                continue
                                
                            # Handle relative URLs
                            if link.startswith('/'):
                                full_link = f"{base_url}{link}"
                            elif not link.startswith('http'):
                                full_link = f"{base_url}/{link}"
                            else:
                                full_link = link
                                
                            # Check domain match
                            try:
                                link_parsed = urlparse(full_link)
                                if link_parsed.netloc == base_domain:
                                    unique_links.add(full_link)
                            except: pass
                        
                        if not unique_links:
                             raise Exception("No sitemap found and no internal links extracted from homepage.")
                             
                        # Construct a "Virtual" XML content for the parser to handle below
                        # This tricks the existing parser logic to process our crawled links
                        warnings.append("No XML Sitemap found. Generated 'Virtual Sitemap' by crawling homepage links.")
                        virtual_xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        for l in unique_links:
                            virtual_xml += f'<url><loc>{l}</loc><priority>0.5</priority></url>'
                        virtual_xml += '</urlset>'
                        
                        content = virtual_xml.encode('utf-8')

                else:
                    content = resp.content
                
                # Handle GZIP (sitemap.xml.gz)
                if sitemap_url.endswith('.gz') or "gzip" in ctype:
                    try:
                        import gzip
                        import io
                        # Check magic header for gzip (1f 8b)
                        if content.startswith(b'\x1f\x8b'):
                            content = gzip.decompress(content)
                    except Exception as gz_err:
                        print(f"Gzip Decompress Failed: {gz_err}")
                        # Continue, maybe it wasn't really gzipped
                
                # Robots Check (Simple heuristic: check host robots.txt)
                robots_status = "unknown"
                try:
                    final_url = str(resp.url)
                    parsed = urlparse(sitemap_url) # Use original base checking
                    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
                    
                    # Add User-Agent to avoid blocks
                    robots_resp = await client.get(robots_url, headers={"User-Agent": "SiteTesterPro/1.0"}, timeout=5.0)
                    
                    if robots_resp.status_code == 200:
                        robots_text = robots_resp.text.lower()
                        s_lower = sitemap_url.lower()
                        f_lower = final_url.lower()
                        
                        # Check both original and final (redirected) URL
                        if s_lower in robots_text or f_lower in robots_text:
                            robots_status = "found"
                        else:
                            # Advanced Check: Sometimes robots.txt uses relative paths (technically invalid but common)
                            # e.g. "Sitemap: /sitemap.xml"
                            path_only = parsed.path.lower()
                            if path_only and f"sitemap: {path_only}" in robots_text:
                                robots_status = "found"
                            else:
                                robots_status = "missing"
                    else:
                        robots_status = "error"
                except Exception as e:
                    print(f"Robots check error: {e}")
                    robots_status = "error"

            except Exception as e:
                # Fatal fetch error
                raise Exception(f"Failed to fetch sitemap: {str(e)}")

        # --- 2. PARSING ---
        root = None
        is_index = False
        child_sitemaps = []
        urls_found = []
        
        try:
            # Attempt 1: Strict Parsing
            try:
                root = ET.fromstring(content)
            except ET.ParseError:
                # Attempt 2: Sanitization
                import re
                txt = content.decode('utf-8', errors='ignore')
                # Replace & not followed by a valid entity
                txt = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-f]+);)', '&amp;', txt)
                # Remove control characters
                txt = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', txt)
                root = ET.fromstring(txt)

            # Detect Type
            ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            if root.tag.endswith('sitemapindex') or 'sitemapindex' in root.tag:
                is_index = True
                for sm in root.findall('.//s:sitemap', ns) or root.findall('sitemap'):
                    loc = sm.find('s:loc', ns) if sm.find('s:loc', ns) is not None else sm.find('loc')
                    if loc is not None and loc.text:
                        child_sitemaps.append(loc.text.strip())
            else:
                for url_entry in root.findall('.//s:url', ns) or root.findall('url'):
                    loc = url_entry.find('s:loc', ns) if url_entry.find('s:loc', ns) is not None else url_entry.find('loc')
                    priority = url_entry.find('s:priority', ns) if url_entry.find('s:priority', ns) is not None else url_entry.find('priority')
                    
                    if loc is not None and loc.text:
                        u_obj = {"loc": loc.text.strip()}
                        if priority is not None and priority.text:
                            try:
                                u_obj["priority"] = float(priority.text)
                            except: pass
                        urls_found.append(u_obj)

        except Exception as e:
            # FAILSAFE: SALVAGE MODE (Regex Extraction)
            print(f"XML Parse Failed, switching to Salvage Mode: {e}")
            warnings.append(f"Invalid XML format ({str(e)}). Used 'Salvage Mode' to extract data.")
            
            import re
            txt_content = content.decode('utf-8', errors='ignore')
            
            # Robust Regex for <loc>, handling <s:loc>, <image:loc>, or whitespace
            # Matches <loc>...</loc>, <s:loc>...</s:loc>, etc.
            # Added re.DOTALL to handle newlines inside tags
            locs = re.findall(r'<(?:\w+:)?loc\s*>(.*?)</(?:\w+:)?loc>', txt_content, re.IGNORECASE | re.DOTALL)
            
            # Clean up whitespace/newlines from extracted URLs
            locs = [l.strip() for l in locs if l.strip()]
            
            # If still nothing, try finding any http/https URL inside tags (Desperate Fallback)
            if not locs:
                 locs = re.findall(r'>(https?://[^<]+)<', txt_content, re.IGNORECASE)
                 if locs:
                     warnings.append("URLs extracted via generic scan (missing scan tags). check structure.")

            # Simple Regex for <sitemapindex>
            if '<sitemapindex' in txt_content or '<s:sitemapindex' in txt_content:
                is_index = True
                child_sitemaps = [l.strip() for l in locs]
            else:
                for l in locs:
                    urls_found.append({"loc": l.strip(), "priority": 0.5})

        if len(urls_found) > 50000:
             errors.append("Sitemap violates strict limit of 50,000 URLs.")

        # --- 3. ORGANIC CHECK (Reachability) ---
        reachability_sample = {}
        if not is_index and urls_found:
            import random
            sample_size = min(len(urls_found), 10) # Sample 10 for speed
            sample = random.sample(urls_found, sample_size)
            
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                for u in sample:
                    try:
                        r = await client.head(u["loc"])
                        reachability_sample[u["loc"]] = r.status_code
                    except:
                        reachability_sample[u["loc"]] = "timeout"

        # --- 4. SCORE CALCULATION ---
        score = 100
        if errors: score -= 20 * len(errors)
        if robots_status == "missing": score -= 10
        if robots_status == "error": score -= 5
        if load_time_ms > 1000: score -= 10
        if load_time_ms > 3000: score -= 20
        
        # Check samples
        dead_links = [s for s, c in reachability_sample.items() if c != 200]
        if dead_links:
            score -= 5 * len(dead_links)
            warnings.append(f"Found {len(dead_links)} broken links in sample (Reachability Check).")

        if score < 0: score = 0
        
        # --- SAVE ---
        avg_pri = 0
        if urls_found:
            pris = [u.get("priority", 0.5) for u in urls_found]
            avg_pri = int((sum(pris) / len(pris)) * 100)

        result = models.SitemapResult(
            session_id=session_id,
            url=sitemap_url,
            is_index=is_index,
            child_sitemaps=json.dumps(child_sitemaps),
            url_count=len(urls_found),
            avg_priority=avg_pri,
            errors=json.dumps(errors),
            warnings=json.dumps(warnings),
            reachability_sample=json.dumps(reachability_sample),
            robots_status=robots_status,
            load_time_ms=load_time_ms,
            score=score
        )
        db.add(result)
        
        session.completed = 1
        session.status = "completed"
        session.completed_at = datetime.utcnow()
        db.commit()

    except Exception as e:
        print(f"Sitemap Audit Error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()


# ========== NEW ROUTES ==========

@app.get("/platform/dashboard", response_class=HTMLResponse)
async def platform_dashboard(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    # Stats
    total_sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).count()
    recent_sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).order_by(models.AuditSession.created_at.desc()).limit(5).all()
    
    # Calculate simple pass rate (mock)
    completed = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id, models.AuditSession.status == "completed").count()
    success_rate = int((completed / total_sessions * 100)) if total_sessions > 0 else 0
    
    # Mock active jobs for now
    active_jobs = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id, models.AuditSession.status == "running").count()

    # Calculate Total Issues Detected
    user_sessions = db.query(models.AuditSession.session_id).filter(models.AuditSession.user_id == user.id).all()
    user_session_ids = [s[0] for s in user_sessions]
    
    total_issues = 0
    if user_session_ids:
        # H1 Issues
        h1_res = db.query(models.H1AuditResult.issues).filter(models.H1AuditResult.session_id.in_(user_session_ids)).all()
        for r in h1_res:
            try:
                issues = json.loads(r[0])
                total_issues += len(issues)
            except: pass
            
        # Phone Issues
        phone_res = db.query(models.PhoneAuditResult.issues).filter(models.PhoneAuditResult.session_id.in_(user_session_ids)).all()
        for r in phone_res:
             try:
                issues = json.loads(r[0])
                total_issues += len(issues)
             except: pass

        # Accessibility Violations
        access_res = db.query(models.AccessibilityAuditResult.violations_count).filter(models.AccessibilityAuditResult.session_id.in_(user_session_ids)).all()
        for r in access_res:
            total_issues += (r[0] or 0)

    # Chart Data (Last 7 Days)
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=6)
    
    daily_sessions = db.query(models.AuditSession)\
        .filter(models.AuditSession.user_id == user.id)\
        .filter(models.AuditSession.created_at >= start_date)\
        .all()
        
    activity_labels = []
    activity_data = []
    
    for i in range(7):
        current_day = start_date + timedelta(days=i)
        # Label: "Mon", "Tue" etc.
        activity_labels.append(current_day.strftime("%a"))
        
        # Count sessions for this day
        count = sum(1 for s in daily_sessions if s.created_at and s.created_at.date() == current_day)
        activity_data.append(count)

    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user": user, 
        "total_sessions": total_sessions,
        "success_rate": success_rate,
        "recent_sessions": recent_sessions,
        "active_jobs": active_jobs,
        "total_issues": total_issues,
        "activity_labels": activity_labels,
        "activity_data": activity_data
    })

@app.get("/platform/device-lab", response_class=HTMLResponse)
async def device_lab_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("device_lab.html", {"request": request, "user": user})

@app.get("/scan/meta-tags", response_class=HTMLResponse)
async def meta_tags_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("meta-tags.html", {"request": request, "user": user})

@app.get("/scan/xml-sitemaps", response_class=HTMLResponse)
async def xml_sitemaps_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("xml-sitemaps.html", {"request": request, "user": user})

@app.get("/platform/history", response_class=HTMLResponse)
async def history_view(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    # Fetch all sessions for history, ordered by newest first
    sessions = db.query(models.AuditSession).filter(
        models.AuditSession.user_id == user.id
    ).order_by(models.AuditSession.created_at.desc()).all()
    
    # Pre-process sessions if needed (e.g. JSON parsing) for the template
    # The existing template seems to expect objects, but let's pass them as is for now
    # equivalent to how dashboard might use them
    
    return templates.TemplateResponse("history.html", {
        "request": request, 
        "user": user,
        "sessions": sessions
    })

@app.get("/platform/visual", response_class=HTMLResponse)
async def visual_test_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("visual_regression.html", {"request": request, "user": user})

@app.get("/platform/profile", response_class=HTMLResponse)
async def profile_view(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    # Fetch simple stats for profile
    total_sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).count()
    completed_audits = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id, models.AuditSession.status == "completed").count()
    
    return templates.TemplateResponse("profile.html", {
        "request": request, 
        "user": user,
        "stats": {
            "total_sessions": total_sessions,
            "completed_audits": completed_audits,
            "success_rate": int((completed_audits / total_sessions * 100)) if total_sessions > 0 else 0
        }
    })

@app.get("/profile")
async def profile_redirect():
    return RedirectResponse(url="/platform/profile")

@app.get("/responsive", response_class=HTMLResponse)
async def responsive_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("responsive.html", {"request": request, "user": user})

@app.get("/responsive/dynamic", response_class=HTMLResponse)
async def dynamic_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("dynamic-audit.html", {"request": request, "user": user})

@app.get("/h1-audit", response_class=HTMLResponse)
async def h1_audit_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("h1-audit.html", {"request": request, "user": user})

@app.get("/phone-audit", response_class=HTMLResponse)
async def phone_audit_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("phone-audit.html", {"request": request, "user": user})

@app.get("/login", response_class=HTMLResponse)
async def login_view(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_view(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_view(request: Request):
    return templates.TemplateResponse("forgot-password.html", {"request": request})

@app.get("/platform/performance", response_class=HTMLResponse)
async def performance_test_view(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    # Fetch recent performance audit results for this user
    recent_results = db.query(models.PerformanceAuditResult).join(
        models.AuditSession, models.PerformanceAuditResult.session_id == models.AuditSession.session_id
    ).filter(
        models.AuditSession.user_id == user.id
    ).order_by(models.PerformanceAuditResult.id.desc()).limit(10).all()
    
    return templates.TemplateResponse("performance_audit.html", {
        "request": request, 
        "user": user,
        "recent_results": recent_results
    })

@app.post("/api/visual-test")
async def trigger_visual_test(
    background_tasks: BackgroundTasks, 
    base_url: str = Form(...), 
    compare_url: str = Form(...), 
    user: models.User = Depends(require_auth), 
    db: Session = Depends(auth.get_db)
):
    session_id = f"vis_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="visual",
        name=f"Visual: {get_unique_filename(base_url)}",
        urls=json.dumps([base_url, compare_url]),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["1280x800"]),
        total_expected=1
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(compare_images_logic, base_url, compare_url, session_id, db)
    
    return JSONResponse({
        "status": "started",
        "session_id": session_id,
        "message": "Visual audit started"
    })

@app.post("/upload/performance")
async def upload_performance(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    strategy: str = Form("desktop"),
    session_name: str = Form("My Performance Audit"),
    db: Session = Depends(auth.get_db)
):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
        
    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="performance",
        name=session_name,
        urls=json.dumps(urls),
        browsers=json.dumps([strategy]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(urls)
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_performance_task, urls, session_id, strategy)
    
    # Store task reference
    running_tasks[session_id] = "performance"

    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "performance"
    })

@app.get("/api/results/{session_id}")
async def get_any_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Generic results endpoint"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    if session.session_type == "visual":
         results = db.query(models.VisualAuditResult).filter_by(session_id=session_id).all()
         response_data = {
             "results": [{"score": r.diff_score, "diff_img": r.diff_image_path} for r in results],
             "dom_diffs": []
         }
         
         # Try to load DOM diff report
         diff_report_path = f"diffs/{session_id}/diff_report.json"
         if os.path.exists(diff_report_path):
             try:
                 with open(diff_report_path, "r") as f:
                     response_data["dom_diffs"] = json.load(f)
             except:
                 pass
                 
         return response_data
         
    elif session.session_type == "performance":
         results = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).all()
         return [{
             "url": r.url,
             "device_preset": r.device_preset,
             "created_at": r.created_at,
             "ttfb": r.ttfb,
             "fcp": r.fcp,
             "score": r.score,
             "page_load": r.page_load
         } for r in results]
         
    elif session.session_type == "accessibility":
        results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
        return [{
            "url": r.url,
            "score": r.score,
            "violations_count": r.violations_count,
            "critical": r.critical_count,
            "serious": r.serious_count,
            "moderate": r.moderate_count,
            "minor": r.minor_count,
            "violations": json.loads(r.report_json) if r.report_json else []
        } for r in results]
    return []

@app.get("/api/results/meta-tags/{session_id}")
async def get_meta_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    results = db.query(models.MetaTagsResult).filter_by(session_id=session_id).all()
    # If no results and session exists, we might return empty list, handled by frontend
    
    return {"results": [{
        "url": r.url,
        "title": r.title,
        "description": r.description,
        "keywords": r.keywords,
        "canonical": r.canonical,
        "og_tags": json.loads(r.og_tags) if r.og_tags else {},
        "twitter_tags": json.loads(r.twitter_tags) if r.twitter_tags else {},
        "schema_tags": json.loads(r.schema_tags) if r.schema_tags else [],
        "missing_tags": json.loads(r.missing_tags) if r.missing_tags else [],
        "warnings": json.loads(r.warnings) if r.warnings else [],
        "keyword_consistency": json.loads(r.keyword_consistency) if r.keyword_consistency else {},
        "score": r.score
    } for r in results]}

@app.get("/api/results/sitemap/{session_id}")
async def get_sitemap_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    r = db.query(models.SitemapResult).filter_by(session_id=session_id).first()
    if not r: return {"results": {}}
    
    return {"results": {
        "url": r.url,
        "is_index": r.is_index,
        "url_count": r.url_count,
        "child_sitemaps": json.loads(r.child_sitemaps) if r.child_sitemaps else [],
        "robots_status": r.robots_status,
        "load_time_ms": r.load_time_ms,
        "score": r.score,
        "errors": json.loads(r.errors) if r.errors else [],
        "warnings": json.loads(r.warnings) if r.warnings else [],
        "reachability_sample": json.loads(r.reachability_sample) if r.reachability_sample else {}
    }}

@app.get("/api/results/h1/{session_id}")
async def get_h1_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
    return [{"url": r.url, "h1_count": r.h1_count, "h1_texts": json.loads(r.h1_texts) if r.h1_texts else [], "issues": json.loads(r.issues) if r.issues else []} for r in results]

@app.get("/progress/h1/{session_id}")
async def h1_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a H1 session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/session-config/static/{session_id}")
async def get_static_session_config(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get static audit session configuration and results with actual file URLs"""
    print(f"[ENTRY] get_static_session_config called for session: {session_id}", flush=True)
    
    user = await get_current_user_from_cookie(request, db)
    print(f"[AUTH] User authenticated: {user is not None}", flush=True)
    if not user:
        raise HTTPException(status_code=401)
    
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    print(f"[DB] Session found: {session is not None}", flush=True)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get all results with actual file paths
    results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
    print(f"[DB] Found {len(results)} StaticAuditResult records", flush=True)
    
    # Parse session data
    urls = json.loads(session.urls) if isinstance(session.urls, str) else session.urls
    browsers = json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers
    resolutions = json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
    print(f"[PARSE] URLs: {len(urls)}, Browsers: {len(browsers)}, Resolutions: {len(resolutions)}", flush=True)
    
    # Build response with actual file URLs from database
    results_map = {}
    for result in results:
        key = f"{result.url}_{result.browser}_{result.resolution}"
        results_map[key] = {
            "url": result.url,
            "browser": result.browser,
            "resolution": result.resolution,
            "screenshot_path": result.screenshot_path,
            "filename": result.filename
        }
    
    print(f"[BUILD] Results map has {len(results_map)} entries", flush=True)
    
    results_list = list(results_map.values()) if results_map else []
    print(f"[BUILD] Results list length: {len(results_list)}", flush=True)
    
    response_data = {
        "urls": urls,
        "browsers": browsers,
        "resolutions": resolutions,
        "results": results_list,
        "type": session.session_type
    }
    
    print(f"[RESPONSE] Keys: {list(response_data.keys())}", flush=True)
    print(f"[RESPONSE] Has results field: {'results' in response_data}", flush=True)
    print(f"[RESPONSE] Results count: {len(response_data.get('results', []))}", flush=True)
    
    # Debug: Print first result if available
    if results_list:
        print(f"[DEBUG] First result filename: {results_list[0].get('filename')}", flush=True)
        print(f"[DEBUG] First result screenshot_path: {results_list[0].get('screenshot_path')}", flush=True)
    
    print(f"[EXIT] Returning response", flush=True)
    
    return response_data


@app.get("/session-config/dynamic/{session_id}")
async def get_dynamic_session_config(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get dynamic audit session configuration and results with actual file URLs"""
    print(f"[ENTRY] get_dynamic_session_config called for session: {session_id}", flush=True)
    
    user = await get_current_user_from_cookie(request, db)
    print(f"[AUTH] User authenticated: {user is not None}", flush=True)
    if not user:
        print("[AUTH] No user - returning 401", flush=True)
        raise HTTPException(status_code=401)
    
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    print(f"[DB] Session found: {session is not None}", flush=True)
    if not session:
        print("[DB] No session - returning 404", flush=True)
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get all results with actual file paths
    results = db.query(models.DynamicAuditResult).filter_by(session_id=session_id).all()
    print(f"[DB] Found {len(results)} DynamicAuditResult records", flush=True)
    
    # Parse session data
    urls = json.loads(session.urls) if isinstance(session.urls, str) else session.urls
    browsers = json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers
    resolutions = json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
    print(f"[PARSE] URLs: {len(urls)}, Browsers: {len(browsers)}, Resolutions: {len(resolutions)}", flush=True)
    
    # Build response with actual file URLs from database
    results_map = {}
    for result in results:
        key = f"{result.url}_{result.browser}_{result.resolution}"
        results_map[key] = {
            "url": result.url,
            "browser": result.browser,
            "resolution": result.resolution,
            "video_path": result.video_path,
            "filename": result.filename
        }
    
    print(f"[BUILD] Results map has {len(results_map)} entries", flush=True)
    
    results_list = list(results_map.values()) if results_map else []
    print(f"[BUILD] Results list length: {len(results_list)}", flush=True)
    
    response_data = {
        "urls": urls,
        "browsers": browsers,
        "resolutions": resolutions,
        "results": results_list,
        "type": session.session_type
    }
    
    print(f"[RESPONSE] Keys: {list(response_data.keys())}", flush=True)
    print(f"[RESPONSE] Has results field: {'results' in response_data}", flush=True)
    print(f"[RESPONSE] Results count: {len(response_data.get('results', []))}", flush=True)
    print(f"[EXIT] Returning response", flush=True)
    
    return response_data


@app.get("/test-code-version")
async def test_code_version():
    """Test endpoint to verify code changes are loaded"""
    return {"version": "2024-01-06-v2", "message": "Code changes loaded successfully!", "results_field_added": True}



@app.get("/platform/accessibility", response_class=HTMLResponse)
async def accessibility_test_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("accessibility-audit.html", {"request": request, "user": user})

@app.post("/upload/accessibility")
async def upload_accessibility(
    request: Request,
    background_tasks: BackgroundTasks,
    urls: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    session_name: str = Form("My Accessibility Audit"),
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    url_list = []
    
    # Process Manual Entry
    if urls:
        url_list.extend([u.strip() for u in urls.splitlines() if u.strip()])

    # Process File Upload
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        url_list.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    url_list = list(dict.fromkeys(url_list))

    if not url_list:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    session_id = f"a11y_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="accessibility",
        name=session_name,
        urls=json.dumps(url_list),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(url_list)
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_accessibility_task, url_list, session_id)
    
    # Store task reference
    running_tasks[session_id] = "accessibility"
    
    return JSONResponse({
        "session": session_id,
        "total_expected": len(url_list),
        "type": "accessibility"
    })

@app.get("/progress/accessibility/{session_id}")
async def accessibility_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of an accessibility session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }


# ========== META TAGS ROUTES ==========

@app.post("/upload/meta-tags")
async def upload_meta_tags(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    session_name: str = Form("My Meta Tags Scan"),
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
        
    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    session_id = f"meta_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="meta-tags",
        name=session_name,
        urls=json.dumps(urls),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(urls)
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_meta_tags_logic, urls, session_id)
    
    # Store task reference
    running_tasks[session_id] = "meta-tags"
    
    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "meta-tags"
    })

@app.get("/progress/meta-tags/{session_id}")
async def meta_tags_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a meta tags session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/api/results/meta-tags/{session_id}")
async def get_meta_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    results = db.query(models.MetaTagsResult).filter_by(session_id=session_id).all()
    
    return {
        "status": session.status,
        "completed": session.completed,
        "total": session.total_expected,
        "results": [{
            "url": r.url,
            "title": r.title,
            "description": r.description,
            "keywords": r.keywords,
            "canonical": r.canonical,
            "score": r.score,
            "og_tags": json.loads(r.og_tags) if r.og_tags else {},
            "twitter_tags": json.loads(r.twitter_tags) if r.twitter_tags else {},
            "schema_tags": json.loads(r.schema_tags) if r.schema_tags else [],
            "missing_tags": json.loads(r.missing_tags) if r.missing_tags else [],
            "warnings": json.loads(r.warnings) if r.warnings else [],
            "keyword_consistency": json.loads(r.keyword_consistency) if r.keyword_consistency else {},
            "created_at": r.created_at
        } for r in results]
    }

@app.get("/scan/meta-tags", response_class=HTMLResponse)
async def meta_tags_page(request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("meta-tags.html", {"request": request, "user": user})


# ========== XML SITEMAP ROUTES ==========

@app.post("/upload/sitemap")
async def upload_sitemap(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    session_name: str = Form("My Sitemap Audit"),
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    clean_url = url.strip()
    if not clean_url:
        return JSONResponse({"error": "No URL provided"}, status_code=400)

    session_id = f"sitemap_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="sitemap",
        name=session_name,
        urls=json.dumps([clean_url]),
        browsers=json.dumps(["None"]),
        resolutions=json.dumps(["Default"]),
        total_expected=1
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_sitemap_logic, clean_url, session_id)
    
    # Store task reference
    running_tasks[session_id] = "sitemap"

    return JSONResponse({
        "session": session_id,
        "total_expected": 1,
        "type": "sitemap"
    })

@app.get("/progress/sitemap/{session_id}")
async def sitemap_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a sitemap session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }


@app.get("/api/results/sitemap/{session_id}")
async def get_sitemap_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    results = db.query(models.SitemapResult).filter_by(session_id=session_id).first()
    
    res_data = {}
    if results:
        res_data = {
            "url": results.url,
            "is_index": results.is_index,
            "child_sitemaps": json.loads(results.child_sitemaps) if results.child_sitemaps else [],
            "url_count": results.url_count,
            "avg_priority": results.avg_priority,
            "errors": json.loads(results.errors) if results.errors else [],
            "warnings": json.loads(results.warnings) if results.warnings else [],
            "reachability_sample": json.loads(results.reachability_sample) if results.reachability_sample else {},
            "robots_status": results.robots_status,
            "load_time_ms": results.load_time_ms,
            "score": results.score,
            "created_at": results.created_at
        }
    
    return {
        "status": session.status,
        "completed": session.completed,
        "results": res_data
    }

@app.get("/scan/xml-sitemaps", response_class=HTMLResponse)
async def sitemap_page(request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("xml-sitemaps.html", {"request": request, "user": user})

@app.get("/accessibility-results/{session_id}")
async def get_accessibility_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
    
    return templates.TemplateResponse("accessibility-results.html", {
        "request": request, 
        "user": user,
        "session": session,
        "results": results
    })


# ========== SESSION CONFIG API ==========

@app.get("/api/session/{session_id}/config")
async def get_session_config(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Get session configuration for restart functionality"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session = db.query(models.AuditSession).filter_by(
        session_id=session_id,
        user_id=user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session.session_id,
        "session_type": session.session_type,
        "name": session.name,
        "urls": json.loads(session.urls) if isinstance(session.urls, str) else session.urls,
        "browsers": json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers,
        "resolutions": json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
    }


@app.get("/session-config/static/{session_id}")
async def get_static_session_config(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Get static audit session configuration and results"""
    print(f"[ENTRY] get_static_session_config called for session: {session_id}")
    try:
        # Get user from cookie
        user = await get_current_user_from_cookie(request, db)
        print(f"[AUTH] User authenticated: {user is not None}")
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Get session
        session = db.query(models.AuditSession).filter_by(
            session_id=session_id,
            user_id=user.id
        ).first()
        
        if not session:
            print(f"[ERROR] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Parse URLs
        urls = json.loads(session.urls) if isinstance(session.urls, str) else session.urls
        browsers = json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers
        resolutions = json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
        
        # Get results from database
        results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
        
        results_data = []
        for result in results:
            results_data.append({
                "url": result.url,
                "browser": result.browser,
                "resolution": result.resolution,
                "screenshot_path": result.screenshot_path,
                "filename": result.filename
            })
        
        print(f"[SUCCESS] Returning {len(urls)} URLs and {len(results_data)} results")
        return {
            "urls": urls,
            "browsers": browsers,
            "resolutions": resolutions,
            "results": results_data
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Exception in get_static_session_config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/session-config/dynamic/{session_id}")
async def get_dynamic_session_config(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Get dynamic audit session configuration and results"""
    try:
        # Get user from cookie
        user = await get_current_user_from_cookie(request, db)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Get session
        session = db.query(models.AuditSession).filter_by(
            session_id=session_id,
            user_id=user.id
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Parse URLs
        urls = json.loads(session.urls) if isinstance(session.urls, str) else session.urls
        browsers = json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers
        resolutions = json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
        
        # Get results from database
        results = db.query(models.DynamicAuditResult).filter_by(session_id=session_id).all()
        
        results_data = []
        for result in results:
            results_data.append({
                "url": result.url,
                "browser": result.browser,
                "resolution": result.resolution,
                "video_path": result.video_path,
                "filename": result.filename
            })
        
        return {
            "urls": urls,
            "browsers": browsers,
            "resolutions": resolutions,
            "results": results_data
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting dynamic session config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== PROXY ENDPOINT ==========

@app.get("/api/proxy")
async def proxy_url(url: str):
    """Proxy endpoint to bypass X-Frame-Options with enhanced compatibility and Playwright fallback"""
    if not url.startswith("http"):
        url = "https://" + url

    async def process_content(content_bytes, final_url, headers):
        """Helper to inject base tag and process headers"""
        # Inject <base> tag for relative links if HTML
        content_type = headers.get("content-type", "").lower()
        if "text/html" in content_type:
            try:
                # Use the final URL after redirects for the base tag
                html = content_bytes.decode("utf-8", errors="replace")
                
                # Inject base tag
                base_tag = f'<base href="{final_url}">'
                
                if "<head>" in html:
                    html = html.replace("<head>", f"<head>{base_tag}", 1)
                elif "<HEAD>" in html:
                    html = html.replace("<HEAD>", f"<HEAD>{base_tag}", 1)
                else:
                    # If no head, prepend to body or html
                    html = base_tag + html
                    
                content_bytes = html.encode("utf-8")
                # Update content-type to ensure utf-8
                if "charset" not in content_type:
                    headers["content-type"] = "text/html; charset=utf-8"
            except Exception as e:
                print(f"Proxy rewrite error: {e}")
                pass
        return content_bytes, headers

    # Mimic a real browser to avoid 403 blocks with httpx
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"'
    }

    try:
        # 1. Try Fast HTTPX Request first
        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            resp = await client.get(url, timeout=15.0, headers=req_headers)
            
            # If rejected by bot protection, trigger fallback
            if resp.status_code in [403, 406, 503, 429]:
                 print(f"Proxy: HTTPX failed with {resp.status_code} for {url}. Falling back to Playwright.")
                 raise Exception("Trigger Playwright Fallback")

            # Filter headers that block iframes or cause encoding issues
            excluded_headers = [
                'x-frame-options', 
                'content-security-policy', 
                'frame-options',
                'content-encoding',
                'transfer-encoding',
                'content-length',
                'connection',
                'strict-transport-security'
            ]
            headers = {
                k: v for k, v in resp.headers.items() 
                if k.lower() not in excluded_headers
            }
            
            content_bytes, headers = await process_content(resp.content, str(resp.url), headers)
            return Response(content=content_bytes, status_code=resp.status_code, headers=headers)
            
    except Exception as e:
        print(f"Proxy HTTPX Error/Fallback: {e}")
        # 2. Playwright Fallback (Slower but handles JS/Bot Protection)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                # Use a specific user agent context
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    # Helper to get full content including iframes/JS modifications? 
                    # Just page.content() is usually enough for static representation
                    content = await page.content()
                    final_url = page.url
                    await browser.close()
                    
                    # Process
                    content_bytes, _ = await process_content(content.encode("utf-8"), final_url, {"content-type": "text/html"})
                    return Response(content=content_bytes, status_code=200, headers={"Content-Type": "text/html"})
                    
                except Exception as p_err:
                    await browser.close()
                    raise p_err
                    
        except Exception as final_err:
            return Response(content=f"Proxy Error: {str(final_err)}", status_code=502)




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)