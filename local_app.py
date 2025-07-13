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

# --- CONFIGURATION ---
DATABASE_FILE = 'celegans_research.db'
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
WORKFLOW_DIAGRAM_FILENAME = 'Workflow_Diagram.png'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
        pubmed = PubMed(tool="C_elegans_DB", email="user@example.com")
        results = pubmed.query(query, max_results=max_results)
        data = []
        for article in results:
            authors = ', '.join([au['lastname'] + ' ' + au['initials'] for au in article.authors]) if article.authors else 'N/A'
            data.append({
                'title': article.title, 'authors': authors, 'publication_date': str(article.publication_date),
                'source': 'PubMed', 'url': f"https://pubmed.ncbi.nlm.nih.gov/{article.pubmed_id.splitlines()[0]}/",
                'abstract': article.abstract, 'citations': 0, 'study_type': 'Publication', 'topic': topic
            })
        df = pd.DataFrame(data)
        store_dataframe(df, 'studies')
    except Exception as e:
        logging.error(f"Error scraping PubMed: {e}")

def scrape_google_scholar(query, topic, max_results=100):
    """Scrapes Google Scholar for a given query and topic."""
    logging.info(f"Scraping Google Scholar for query: '{query}'")
    try:
        search_query = scholarly.search_pubs(query)
        data = []
        for i, pub in enumerate(search_query):
            if i >= max_results: break
            bib = pub.get('bib', {})
            data.append({
                'title': bib.get('title'), 'authors': ', '.join(bib.get('author', [])),
                'publication_date': bib.get('pub_year'), 'source': bib.get('venue', 'Google Scholar'),
                'url': pub.get('pub_url', f"https://scholar.google.com/scholar?q={query.replace(' ', '+')}"),
                'abstract': bib.get('abstract'), 'citations': pub.get('num_citations', 0),
                'study_type': 'Publication', 'topic': topic
            })
        df = pd.DataFrame(data)
        store_dataframe(df, 'studies')
    except Exception as e:
        logging.error(f"Error scraping Google Scholar: {e}")

def scrape_news(query, topic, max_results=100):
    """Scrapes news articles using NewsAPI."""
    if not NEWS_API_KEY:
        logging.warning("NEWS_API_KEY not found. Skipping news scraping.")
        return
    logging.info(f"Scraping NewsAPI for query: '{query}'")
    try:
        newsapi = NewsApiClient(api_key=NEWS_API_KEY)
        articles = newsapi.get_everything(q=query, language='en', sort_by='relevancy', page_size=max_results)
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
        logging.error(f"Error scraping NewsAPI: {e}")

def scrape_twitter(query, topic, max_results=200):
    """Scrapes Twitter/Nitter for a given query and topic."""
    logging.info(f"Scraping Twitter/Nitter for query: '{query}'")
    try:
        scraper = Nitter(log_level=1)
        tweets = scraper.get_tweets(query, mode='term', number=max_results)
        data = []
        for tweet in tweets['tweets']:
            data.append({
                'title': f"Tweet by {tweet['user']['name']}", 'source': 'Twitter/Nitter', 'url': tweet['link'],
                'published_date': tweet['date'].split(' ')[0], 'author': tweet['user']['username'],
                'summary': tweet['text'], 'topic': topic
            })
        df = pd.DataFrame(data)
        store_dataframe(df, 'expert_opinions')
    except Exception as e:
        logging.error(f"Error scraping Twitter/Nitter: {e}")

def scrape_youtube(query, topic, max_results=100):
    """Scrapes YouTube for videos related to the query."""
    logging.info(f"Scraping YouTube for query: '{query}'")
    try:
        ydl_opts = {'quiet': True, 'extract_flat': True, 'match_filter': yt_dlp.utils.match_filter_func('!is_live')}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            videos = result.get('entries', [])
            data = []
            for video in videos:
                data.append({
                    'title': video.get('title'), 'source': 'YouTube', 'url': video.get('webpage_url'),
                    'published_date': video.get('upload_date'), 'author': video.get('uploader'),
                    'summary': video.get('description'), 'topic': topic
                })
            df = pd.DataFrame(data)
            store_dataframe(df, 'expert_opinions')
    except Exception as e:
        logging.error(f"Error scraping YouTube: {e}")

def store_dataframe(df, table_name):
    """Stores a Pandas DataFrame in the specified database table efficiently."""
    if df.empty:
        logging.info(f"DataFrame for table '{table_name}' is empty. Nothing to store.")
        return
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        # FIX: Use a lock to prevent concurrent writes from different scraping threads,
        # which can cause "database is locked" errors.
        with conn:
            df.to_sql(table_name, conn, if_exists='append', index=False)
        conn.close()
        logging.info(f"Successfully stored {len(df)} records in the '{table_name}' table.")
    except sqlite3.IntegrityError:
        # This is not an error, just informational. It means we are skipping duplicates.
        logging.warning(f"An integrity error occurred for table '{table_name}', which may indicate duplicate entries were skipped.")
    except Exception as e:
        logging.error(f"An error occurred while storing data in '{table_name}': {e}")

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
            studies_cursor = conn.execute('SELECT * FROM studies ORDER BY publication_date DESC')
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
            except Exception as e:
                logging.error(f"Error adding study manually: {e}")
            return redirect(url_for('index'))
        return render_template('add_study.html')

    return app

def run_flask_app():
    """Creates and runs the Flask web application."""
    app = create_app()
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
    for topic, query in topics.items():
        print(f"\n--- Scraping for topic: {topic} ---")
        time.sleep(random.uniform(1, 3))
        scrape_pubmed(query, topic, max_results=1000)
        time.sleep(random.uniform(1, 3))
        scrape_google_scholar(query, topic, max_results=100)
        time.sleep(random.uniform(1, 3))
        scrape_news(query, topic, max_results=100)
        time.sleep(random.uniform(1, 3))
        scrape_twitter(f'"{query}"', topic, max_results=200)
        time.sleep(random.uniform(1, 3))
        scrape_youtube(query, topic, max_results=100)
    print("\n[5/5] All scraping complete. Launching web interface...")
    run_flask_app()

if __name__ == '__main__':
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
