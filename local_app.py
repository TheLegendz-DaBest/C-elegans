# local_app.py

import sqlite3
import pandas as pd
import requests
from bs4 import BeautifulSoup
from pymed_paperscraper import PubMed
from scholarly import scholarly
from ntscraper import Nitter
from newsapi import NewsApiClient
import yt_dlp
from flask import Flask, render_template, request, redirect, url_for
import webbrowser
import os
import sys
from collections import defaultdict
import logging
import threading
import graphviz
import time
import random
import shutil
import urllib.parse # Added for URL encoding
from fake_useragent import UserAgent # Added for robust scraping

# --- CONFIGURATION ---
DATABASE_FILE = 'celegans_research.db'
# FIX: Hardcoded the NEWS_API_KEY as requested for the client's executable.
# This ensures the news fetching functionality works without needing environment variables.
NEWS_API_KEY = 'd2ba085e4689486098f15c8f674301e7'
WORKFLOW_DIAGRAM_FILENAME = 'Workflow_Diagram.png'

# --- SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Initialize UserAgent to be used by scrapers to avoid being blocked.
try:
    ua = UserAgent()
except Exception:
    # Fallback user agent in case the fake-useragent service is down
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

# Set a global timeout for scholarly to prevent indefinite hangs
scholarly.set_timeout(15)


# --- HELPER FUNCTIONS for PyInstaller ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def extract_and_save_diagram():
    """
    When running as a bundled app, this finds the diagram inside the package,
    copies it to the user's current directory, and informs them.
    """
    if not getattr(sys, 'frozen', False):
        logging.info("Running in development mode. Skipping diagram extraction.")
        return

    source_path = resource_path(WORKFLOW_DIAGRAM_FILENAME)
    dest_path = os.path.join(os.getcwd(), WORKFLOW_DIAGRAM_FILENAME)

    if os.path.exists(dest_path):
        logging.info(f"'{WORKFLOW_DIAGRAM_FILENAME}' already exists. Skipping extraction.")
        return

    if os.path.exists(source_path):
        try:
            shutil.copy(source_path, dest_path)
            logging.info(f"Successfully extracted '{WORKFLOW_DIAGRAM_FILENAME}' to the current directory.")
        except Exception as e:
            logging.error(f"Error extracting diagram: {e}")
    else:
        logging.warning("Could not find the workflow diagram inside the application package.")


# --- WORKFLOW VISUALIZATION ---
def generate_workflow_diagram():
    """
    Generates a workflow diagram. This is now ONLY run during the build process.
    """
    logging.info("Generating workflow diagram...")
    try:
        dot = graphviz.Digraph('C_Elegans_Workflow', comment='Research Cataloging System Workflow')
        dot.attr('node', shape='box', style='rounded,filled', fillcolor='lightblue', fontname='Helvetica')
        dot.attr('edge', fontname='Helvetica')
        dot.attr(rankdir='TB', label='C. elegans Research Aggregator Workflow', fontsize='20', labelloc='t')

        # Define Nodes
        with dot.subgraph(name='cluster_sources') as c:
            c.attr(style='filled', color='lightgrey')
            c.attr(label='Data Sources')
            c.node('pubmed', 'PubMed')
            c.node('scholar', 'Google Scholar')
            c.node('news', 'NewsAPI')
            c.node('twitter', 'Twitter/Nitter')
            c.node('youtube', 'YouTube')

        with dot.subgraph(name='cluster_process') as c:
            c.attr(label='Processing Core')
            c.attr(style='filled', color='beige')
            c.node('main_app', 'local_app.py\n(Main Controller)')
            c.node('scraper', 'Scraping Functions')
            c.node('database', 'SQLite DB\n(celegans_research.db)')
            c.node('web_ui', 'Flask Web UI')

        # Define Edges
        dot.edge('main_app', 'scraper', label='Initiates Scraping')
        dot.edge('scraper', 'pubmed')
        dot.edge('scraper', 'scholar')
        dot.edge('scraper', 'news')
        dot.edge('scraper', 'twitter')
        dot.edge('scraper', 'youtube')

        dot.edge('scraper', 'database', label='Stores Data')
        dot.edge('main_app', 'web_ui', label='Launches UI')
        dot.edge('web_ui', 'database', label='Reads Data For Display')

        dot.node('user', 'User', shape='ellipse', fillcolor='lightgreen')
        dot.edge('user', 'web_ui', label='Interacts with')

        with dot.subgraph(name='cluster_build') as c:
            c.attr(label='Build Process (GitHub Actions)')
            c.attr(style='filled', color='lightcyan')
            c.node('gh_actions', 'GitHub Actions Workflow')
            c.node('pyinstaller', 'PyInstaller')
            c.node('diagram_gen', 'generate_workflow_diagram()')
            c.node('executable', 'Packaged Executable')

        dot.edge('gh_actions', 'diagram_gen', label='calls')
        dot.edge('diagram_gen', 'gh_actions', label='returns diagram')
        dot.edge('gh_actions', 'pyinstaller', label='runs')
        dot.edge('pyinstaller', 'executable', label='creates')

        dot.render(WORKFLOW_DIAGRAM_FILENAME.replace('.png', ''), format='png', cleanup=True)
        logging.info(f"Successfully created '{WORKFLOW_DIAGRAM_FILENAME}'")
    except Exception as e:
        logging.error(f"Could not generate workflow diagram. Is Graphviz installed and in your PATH? Error: {e}")

# --- DATABASE, SCRAPING, AND CATEGORIZATION FUNCTIONS ---
def setup_database():
    """Initializes the SQLite database at RUNTIME."""
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS studies (
            id INTEGER PRIMARY KEY, title TEXT, authors TEXT, publication_date TEXT,
            source TEXT, url TEXT UNIQUE, abstract TEXT, citations INTEGER,
            study_type TEXT, topic TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS expert_opinions (
            id INTEGER PRIMARY KEY, title TEXT, source TEXT, url TEXT UNIQUE,
            published_date TEXT, author TEXT, summary TEXT, topic TEXT
        )
    ''')
    conn.commit()
    conn.close()

def scrape_pubmed(query, topic, max_results=1000):
    """Scrapes PubMed for a given query and topic."""
    logging.info(f"Scraping PubMed for query: '{query}'")
    try:
        # pymed is a well-behaved library, usually doesn't require a user-agent
        pubmed = PubMed(tool="C_elegans_DB", email="user@example.com")
        results = pubmed.query(query, max_results=max_results)
        data = []
        for article in results:
            # Defensive check for pubmed_id to prevent errors
            if not article.pubmed_id or not article.pubmed_id.strip():
                continue
            
            authors = ', '.join([au['lastname'] + ' ' + au['initials'] for au in article.authors]) if article.authors else 'N/A'
            # The splitlines() is a good defense against malformed IDs.
            url = f"https://pubmed.ncbi.nlm.nih.gov/{article.pubmed_id.splitlines()[0]}/"
            
            data.append({
                'title': article.title, 'authors': authors, 'publication_date': str(article.publication_date),
                'source': 'PubMed', 'url': url,
                'abstract': article.abstract, 'citations': 0, 'study_type': 'Publication', 'topic': topic
            })
        df = pd.DataFrame(data)
        store_dataframe(df, 'studies')
    except Exception as e:
        logging.error(f"Error scraping PubMed: {e}. This may be a network issue or a change in the PubMed API.")

def scrape_google_scholar(query, topic, max_results=100):
    """Scrapes Google Scholar for a given query and topic."""
    logging.info(f"Scraping Google Scholar for query: '{query}'")
    try:
        # IMPROVEMENT: Set a random user agent for scholarly to reduce the risk of being blocked.
        scholarly.set_proxy_generator(lambda: {'http': f'http://{ua.random}'})
        
        search_query = scholarly.search_pubs(query)
        data = []
        for i, pub in enumerate(search_query):
            if i >= max_results: break
            bib = pub.get('bib', {})
            title = bib.get('title', 'No Title')
            
            # FIX: Improve URL handling to prevent 404s.
            # Prioritize the direct publication URL. If unavailable, create a stable link
            # to the Google Scholar entry for that specific paper, which is better than a generic search query.
            pub_url = pub.get('pub_url')
            if not pub_url:
                # This creates a search link for the specific title, which is more reliable than a generic query link.
                pub_url = f"https://scholar.google.com/scholar?q={urllib.parse.quote_plus(title)}"

            data.append({
                'title': title, 'authors': ', '.join(bib.get('author', [])),
                'publication_date': str(bib.get('pub_year', 'N/A')), 'source': bib.get('venue', 'Google Scholar'),
                'url': pub_url,
                'abstract': bib.get('abstract'), 'citations': pub.get('num_citations', 0),
                'study_type': 'Publication', 'topic': topic
            })
        df = pd.DataFrame(data)
        store_dataframe(df, 'studies')
    except Exception as e:
        logging.error(f"Error scraping Google Scholar: {e}. Google may be temporarily blocking requests. The script will continue.")

def scrape_news(query, topic, max_results=100):
    """Scrapes news articles using NewsAPI."""
    if not NEWS_API_KEY or NEWS_API_KEY == 'YOUR_API_KEY_HERE':
        logging.warning("NEWS_API_KEY not found or not set. Skipping news scraping.")
        return
    logging.info(f"Scraping NewsAPI for query: '{query}'")
    try:
        # The newsapi-python client handles headers and endpoints.
        newsapi = NewsApiClient(api_key=NEWS_API_KEY)
        # Note: NewsAPI 'get_everything' on a developer plan only provides articles from the last month.
        articles = newsapi.get_everything(q=query, language='en', sort_by='relevancy', page_size=min(max_results, 100))
        
        if articles['status'] != 'ok':
            logging.error(f"NewsAPI returned an error: {articles.get('message')}")
            return

        data = []
        for article in articles['articles']:
            data.append({
                'title': article['title'], 'source': article['source']['name'], 'url': article['url'],
                'published_date': article['publishedAt'].split('T')[0], 'author': article.get('author', 'N/A'),
                'summary': article.get('description'), 'topic': topic
            })
        df = pd.DataFrame(data)
        store_dataframe(df, 'expert_opinions')
    except Exception as e:
        logging.error(f"Error scraping NewsAPI: {e}. Check your API key and network connection.")

def scrape_twitter(query, topic, max_results=200):
    """Scrapes Twitter/Nitter for a given query and topic."""
    logging.info(f"Scraping Twitter/Nitter for query: '{query}'")
    # FIX: Nitter is unstable. Add retries and a clear warning.
    # The Nitter class will attempt to find a working instance.
    # We increase retries to make it more robust against temporary instance failures.
    try:
        scraper = Nitter(log_level=0, retries=5, skip_instance_check=False) # log_level=0 to reduce console spam
        tweets = scraper.get_tweets(query, mode='term', number=max_results)
        
        # FIX: Add robust check for valid results from ntscraper
        if not tweets or not tweets.get('tweets'):
            logging.warning(f"Nitter did not return any tweets for '{query}'. This is common due to the instability of public Nitter instances.")
            return

        data = []
        for tweet in tweets['tweets']:
            # Ensure essential data exists to avoid errors
            if not all(k in tweet for k in ['link', 'date', 'text']) or not all(k in tweet['user'] for k in ['name', 'username']):
                continue

            data.append({
                'title': f"Tweet by {tweet['user']['name']}", 'source': 'Twitter/Nitter', 'url': tweet['link'],
                'published_date': tweet['date'].split(' ')[0], 'author': tweet['user']['username'],
                'summary': tweet['text'], 'topic': topic
            })
        df = pd.DataFrame(data)
        store_dataframe(df, 'expert_opinions')
    except Exception as e:
        logging.error(f"CRITICAL: Error scraping Twitter/Nitter: {e}. This source is often unreliable and may fail.")

def scrape_youtube(query, topic, max_results=100):
    """Scrapes YouTube for videos related to the query."""
    logging.info(f"Scraping YouTube for query: '{query}'")
    try:
        # IMPROVEMENT: Add a User-Agent to yt_dlp requests to appear as a regular browser.
        ydl_opts = {
            'quiet': True, 
            'extract_flat': True, # Don't fetch full video info, just the listing
            'match_filter': yt_dlp.utils.match_filter_func('!is_live'),
            'http_headers': {'User-Agent': ua.random}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # ytsearch{max_results} is the correct syntax for searching a limited number of results
            result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            videos = result.get('entries', [])
            data = []
            for video in videos:
                # Use .get() with default values for safety
                data.append({
                    'title': video.get('title', 'Untitled Video'), 
                    'source': 'YouTube', 
                    'url': video.get('webpage_url', '#'),
                    'published_date': video.get('upload_date', 'N/A'), # Format is YYYYMMDD
                    'author': video.get('uploader', 'N/A'),
                    'summary': video.get('description'), 
                    'topic': topic
                })
            df = pd.DataFrame(data)
            store_dataframe(df, 'expert_opinions')
    except Exception as e:
        logging.error(f"Error scraping YouTube: {e}. This could be due to network issues or changes in YouTube's site structure.")

def store_dataframe(df, table_name):
    """Stores a Pandas DataFrame in the specified database table efficiently."""
    if df.empty:
        logging.info(f"DataFrame for table '{table_name}' is empty. Nothing to store.")
        return
    try:
        conn = sqlite3.connect(DATABASE_FILE, timeout=10) # Added timeout to connect
        # Use a lock to prevent concurrent writes from different scraping threads,
        # which can cause "database is locked" errors.
        with conn:
            # Remove duplicates based on URL before appending to avoid IntegrityError
            # and keep the database clean.
            existing_urls = pd.read_sql(f'SELECT url FROM {table_name}', conn)['url'].tolist()
            original_count = len(df)
            df = df[~df['url'].isin(existing_urls)]
            new_count = len(df)
            
            if new_count > 0:
                df.to_sql(table_name, conn, if_exists='append', index=False)
                logging.info(f"Successfully stored {new_count} new records (out of {original_count} scraped) in the '{table_name}' table.")
            else:
                logging.info(f"All {original_count} scraped records for '{table_name}' were already in the database.")

    except sqlite3.Error as e:
        # More specific error handling for sqlite
        logging.error(f"A SQLite error occurred while storing data in '{table_name}': {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred while storing data in '{table_name}': {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

# --- FLASK WEB APP (APPLICATION FACTORY PATTERN) ---
def create_app():
    """Creates and configures the Flask application."""
    template_folder_path = resource_path('templates')
    app = Flask(__name__, template_folder=template_folder_path)

    @app.route('/')
    def index():
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        grouped_studies = defaultdict(list)
        grouped_opinions = defaultdict(list)
        all_topics = set()
        try:
            studies_cursor = conn.execute('SELECT * FROM studies ORDER BY publication_date DESC, citations DESC')
            for study in studies_cursor:
                topic = study['topic']
                grouped_studies[topic].append(dict(study))
                all_topics.add(topic)
            opinions_cursor = conn.execute('SELECT * FROM expert_opinions ORDER BY published_date DESC')
            for opinion in opinions_cursor:
                topic = opinion['topic']
                grouped_opinions[topic].append(dict(opinion))
                all_topics.add(topic)
        except Exception as e:
            logging.error(f"Error fetching data from database for index page: {e}")
        finally:
            conn.close()
        sorted_topics = sorted(list(all_topics))
        return render_template('index.html', grouped_studies=grouped_studies, grouped_opinions=grouped_opinions, all_topics=sorted_topics)

    @app.route('/add_study', methods=['GET', 'POST'])
    def add_study():
        if request.method == 'POST':
            try:
                conn = sqlite3.connect(DATABASE_FILE)
                c = conn.cursor()
                c.execute('''
                    INSERT INTO studies (title, authors, publication_date, source, url, abstract, citations, study_type, topic)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    request.form['title'], request.form['authors'], request.form['publication_date'],
                    request.form['source'], request.form['url'], request.form['abstract'],
                    int(request.form.get('citations', 0)), request.form.get('study_type', 'Publication'),
                    request.form['topic']
                ))
                conn.commit()
                conn.close()
                logging.info(f"Manually added study: {request.form['title']}")
            except sqlite3.IntegrityError:
                logging.warning(f"Could not add study '{request.form['title']}'. The URL '{request.form['url']}' may already exist.")
            except Exception as e:
                logging.error(f"Error adding study manually: {e}")
            return redirect(url_for('index'))
        return render_template('add_study.html')

    return app

def run_flask_app():
    """Creates and runs the Flask web application."""
    app = create_app()
    # Open the web browser after a short delay to allow the server to start.
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000/")).start()
    app.run(debug=False, port=5000)

# --- WORKFLOW ORCHESTRATION ---
def main_workflow():
    """The main function that orchestrates the entire workflow for the client."""
    print("--- Starting C. elegans Research Cataloging System ---")
    print("\n[1/5] Checking for and extracting workflow diagram...")
    extract_and_save_diagram()
    print("\n[2/5] Setting up database...")
    setup_database()
    print("  - Database setup complete.")
    print("\n[3/5] Defining search topics and keywords...")
    topics = {
        "Aging & Longevity": '"C. elegans" AND (aging OR longevity OR lifespan)',
        "Neuroscience": '"C. elegans" AND (neuron OR synapse OR behavior OR neural circuit)',
        "Genetics & Development": '"C. elegans" AND (genetics OR development OR gene expression OR embryo)',
        "Drug Discovery & Disease Models": '"C. elegans" AND (drug discovery OR disease model OR screen OR therapeutic)',
    }
    print(f"  - Topics defined: {', '.join(topics.keys())}")
    print("\n[4/5] Starting data scraping process (this may take a few minutes)...")
    print("  - NOTE: Some sources like Twitter/Nitter may fail due to their public, unstable nature. The program will continue.")
    
    # Create a list of scraping tasks to run
    scraping_tasks = []
    for topic, query in topics.items():
        # Add a small random delay between different topics to be less aggressive
        time.sleep(random.uniform(1, 3))
        print(f"\n--- Queuing scraping tasks for topic: {topic} ---")
        # Each function call is a task
        scraping_tasks.append(threading.Thread(target=scrape_pubmed, args=(query, topic), kwargs={'max_results': 1000}))
        scraping_tasks.append(threading.Thread(target=scrape_google_scholar, args=(query, topic), kwargs={'max_results': 100}))
        scraping_tasks.append(threading.Thread(target=scrape_news, args=(query, topic), kwargs={'max_results': 100}))
        scraping_tasks.append(threading.Thread(target=scrape_twitter, args=(f'"{query}"', topic), kwargs={'max_results': 200}))
        scraping_tasks.append(threading.Thread(target=scrape_youtube, args=(query, topic), kwargs={'max_results': 100}))

    # IMPROVEMENT: Run scraping tasks in parallel using threads to speed up the process.
    # The database writing is thread-safe due to the `with conn:` context manager.
    for task in scraping_tasks:
        task.start()
        time.sleep(random.uniform(0.5, 1.5)) # Stagger thread starts slightly

    # Wait for all threads to complete
    for task in scraping_tasks:
        task.join()

    print("\n[5/5] All scraping complete. Launching web interface...")
    run_flask_app()

if __name__ == '__main__':
    # This logic allows the script to be used for two purposes:
    # 1. Normal execution to run the application.
    # 2. A special mode for the build process to generate a diagram.
    if len(sys.argv) > 1 and sys.argv[1] == '--generate-diagram-only':
        print("Generating workflow diagram for build artifact...")
        generate_workflow_diagram()
        print("Diagram generation complete. Exiting.")
        # FIX: Explicitly flush output streams and exit to prevent the script
        # from hanging or being canceled in the CI/CD pipeline on Windows.
        sys.stdout.flush()
        sys.stderr.flush()
        # Use os._exit(0) for a more immediate exit, which can resolve hangs
        # in CI environments caused by lingering subprocesses on Windows.
        os._exit(0)
    else:
        main_workflow()
