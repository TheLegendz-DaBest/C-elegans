# local_app.py

import sqlite3
import pandas as pd
import requests
from bs4 import BeautifulSoup
from pymed import PubMed
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

# --- CONFIGURATION ---
DATABASE_FILE = 'celegans_research.db'
# Load NewsAPI Key from environment variable for security.
# The GitHub Actions workflow will set this variable.
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
WORKFLOW_DIAGRAM_FILE = 'Workflow_Diagram'

# Setup logging to monitor the scraping process
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper function to find data files (for PyInstaller) ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- WORKFLOW VISUALIZATION ---
def generate_workflow_diagram():
    """
    Generates a workflow diagram using Graphviz and saves it as a PNG.
    """
    logging.info("Generating workflow diagram...")
    try:
        dot = graphviz.Digraph('C_Elegans_Workflow', comment='Research Cataloging System Workflow')
        dot.attr('node', shape='box', style='rounded,filled', fillcolor='lightblue', fontname='Helvetica')
        dot.attr('edge', fontname='Helvetica')
        dot.attr(rankdir='TB', label='C. elegans Research Aggregator Workflow', fontsize='20')

        # Define Nodes
        with dot.subgraph(name='cluster_0') as c:
            c.attr(style='filled', color='lightgrey')
            c.node_attr.style = 'filled'
            c.node_attr.fillcolor = 'white'
            c.attr(label='Data Scraping & Collection (Thousands of entries)')
            c.node('start', 'Start', shape='ellipse', fillcolor='palegreen')
            c.node('keywords', 'Define Expanded\nKeyword List', shape='folder', fillcolor='khaki')
            c.node('pubmed', 'Scrape PubMed')
            c.node('gscholar', 'Scrape Google Scholar')
            c.node('experts', 'Scrape Expert Opinions\n(News, YouTube, Twitter)')
            c.node('manual', 'Manual Study Entry Form')

        with dot.subgraph(name='cluster_1') as c:
            c.attr(style='filled', color='lightgrey')
            c.node_attr.style = 'filled'
            c.node_attr.fillcolor = 'white'
            c.attr(label='Data Processing & Storage')
            c.node('db', 'Store & Update\nSQLite Database\n(Handles Duplicates)', shape='cylinder', fillcolor='orange')
            c.node('categorize', 'Categorize Entries\nby Keyword')

        with dot.subgraph(name='cluster_2') as c:
            c.attr(style='filled', color='lightgrey')
            c.node_attr.style = 'filled'
            c.node_attr.fillcolor = 'white'
            c.attr(label='User Interface')
            c.node('webapp', 'Launch Local\nFlask Web App', shape='house', fillcolor='lightpink')
            c.node('browser', 'View & Filter Data\nin Web Browser', shape='ellipse', fillcolor='palegreen')

        # Define Edges
        dot.edge('start', 'keywords')
        dot.edge('keywords', 'pubmed')
        dot.edge('keywords', 'gscholar')
        dot.edge('keywords', 'experts')
        dot.edge('manual', 'db')
        dot.edge('pubmed', 'db')
        dot.edge('gscholar', 'db')
        dot.edge('experts', 'db')
        dot.edge('db', 'categorize')
        dot.edge('categorize', 'webapp')
        dot.edge('webapp', 'browser')

        # Render the diagram
        dot.render(WORKFLOW_DIAGRAM_FILE, format='png', cleanup=True)
        logging.info(f"Successfully created '{WORKFLOW_DIAGRAM_FILE}.png'")
    except Exception as e:
        logging.error(f"Could not generate workflow diagram. Please ensure Graphviz is installed and in your system's PATH. Error: {e}")

# --- DATABASE, SCRAPING, AND CATEGORIZATION FUNCTIONS ---
def setup_database():
    """Initializes the SQLite database and creates tables if they don't exist."""
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    # Main table for scientific publications
    c.execute('''
        CREATE TABLE IF NOT EXISTS studies (
            id INTEGER PRIMARY KEY, title TEXT, authors TEXT, publication_date TEXT,
            source TEXT, url TEXT UNIQUE, abstract TEXT, citations INTEGER,
            study_type TEXT, topic TEXT
        )
    ''')
    # Table for news, blogs, social media, etc.
    c.execute('''
        CREATE TABLE IF NOT EXISTS expert_opinions (
            id INTEGER PRIMARY KEY, title TEXT, source TEXT, url TEXT UNIQUE,
            published_date TEXT, author TEXT, summary TEXT, topic TEXT
        )
    ''')
    conn.commit()
    conn.close()

def scrape_pubmed(query, topic, max_results=1000):
    """Scrapes PubMed for a given query."""
    logging.info(f"Querying PubMed for up to {max_results} results on: '{query}'")
    try:
        pubmed = PubMed(tool="C-Elegans-DB", email="user@example.com")
        results = pubmed.query(query, max_results=max_results)
        articles = []
        for article in results:
            article_data = article.toDict()
            articles.append({
                'title': article_data.get('title'),
                'authors': ', '.join(author['lastname'] + ' ' + author['initials'] for author in article_data.get('authors', []) if author.get('lastname') and author.get('initials')),
                'publication_date': str(article_data.get('publication_date')),
                'source': 'PubMed',
                'url': f"https://pubmed.ncbi.nlm.nih.gov/{article_data.get('pubmed_id').splitlines()[0]}/",
                'abstract': article_data.get('abstract'),
                'citations': 0,  # PubMed API doesn't provide citation counts
                'study_type': 'Publication',
                'topic': topic
            })
        return pd.DataFrame(articles)
    except Exception as e:
        logging.error(f"Error scraping PubMed for '{query}': {e}")
        return pd.DataFrame()

def scrape_google_scholar(query, topic, max_results=1000):
    """Scrapes Google Scholar, respecting delays to avoid being blocked."""
    logging.info(f"Querying Google Scholar for up to {max_results} results on: '{query}'")
    try:
        search_query = scholarly.search_pubs(query)
        publications = []
        for i, pub in enumerate(search_query):
            if i >= max_results:
                break
            publications.append({
                'title': pub['bib'].get('title'),
                'authors': ', '.join(pub['bib'].get('author', [])),
                'publication_date': str(pub['bib'].get('pub_year')),
                'source': 'Google Scholar',
                'url': pub.get('pub_url') or pub.get('eprint_url', f"https://scholar.google.com/scholar?q={pub['bib'].get('title').replace(' ', '+')}"),
                'abstract': pub['bib'].get('abstract'),
                'citations': pub.get('num_citations', 0),
                'study_type': 'Publication',
                'topic': topic
            })
            # IMPORTANT: Wait between requests to avoid getting blocked by Google.
            time.sleep(random.uniform(1.5, 3.5))
        return pd.DataFrame(publications)
    except Exception as e:
        logging.error(f"Error scraping Google Scholar for '{query}': {e}")
        return pd.DataFrame()

def scrape_news(query, topic, max_results=100):
    """Scrapes news articles using NewsAPI."""
    if not NEWS_API_KEY:
        logging.warning("NEWS_API_KEY environment variable not set. Skipping NewsAPI scraping.")
        return pd.DataFrame()
        
    logging.info(f"Querying NewsAPI for: '{query}'")
    try:
        newsapi = NewsApiClient(api_key=NEWS_API_KEY)
        # Note: NewsAPI developer plan on 'get_everything' is limited to 100 results per query.
        articles = newsapi.get_everything(q=query, language='en', sort_by='relevancy', page_size=min(max_results, 100))
        news_items = []
        for article in articles['articles']:
            news_items.append({
                'title': article.get('title'),
                'source': article['source']['name'],
                'url': article.get('url'),
                'published_date': article.get('publishedAt'),
                'author': article.get('author'),
                'summary': article.get('description'),
                'topic': topic
            })
        return pd.DataFrame(news_items)
    except Exception as e:
        logging.error(f"Error scraping NewsAPI for '{query}': {e}")
        return pd.DataFrame()

def scrape_twitter(query, topic, max_results=200):
    """
    Scrapes Twitter/X using Nitter.
    Note: This relies on public Nitter instances and may be unreliable.
    """
    logging.info(f"Querying Twitter/X for: '{query}'")
    try:
        scraper = Nitter()
        tweets = scraper.get_tweets(query, mode='term', number=max_results)
        tweet_items = []
        for tweet in tweets['tweets']:
            tweet_items.append({
                'title': f"Tweet by {tweet['user']['name']}",
                'source': 'Twitter/X',
                'url': tweet.get('link'),
                'published_date': tweet.get('date'),
                'author': tweet['user']['username'],
                'summary': tweet.get('text'),
                'topic': topic
            })
        return pd.DataFrame(tweet_items)
    except Exception as e:
        logging.error(f"Error scraping Twitter/X for '{query}'. This scraper can be unreliable. Error: {e}")
        return pd.DataFrame()

def scrape_youtube(query, topic, max_results=100):
    """Scrapes YouTube video information using yt-dlp without an API key."""
    logging.info(f"Querying YouTube for: '{query}'")
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,  # Don't download, just get metadata
        'force_generic_extractor': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # The f"ytsearch{max_results}:" syntax fetches a specific number of search results.
            result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            videos = []
            if 'entries' in result:
                for entry in result['entries']:
                    if entry:
                        videos.append({
                            'title': entry.get('title'),
                            'source': 'YouTube',
                            'url': f"https://www.youtube.com/watch?v={entry.get('id')}",
                            'published_date': None,  # Search results don't include publish date
                            'author': entry.get('uploader'),
                            'summary': entry.get('description'),
                            'topic': topic
                        })
            return pd.DataFrame(videos)
    except Exception as e:
        logging.error(f"Error scraping YouTube for '{query}': {e}")
        return pd.DataFrame()

def store_dataframe(df, table_name):
    """Stores a pandas DataFrame into the specified database table, ignoring duplicates."""
    if df.empty:
        return
    conn = sqlite3.connect(DATABASE_FILE)
    # The 'url' column has a UNIQUE constraint. We insert row-by-row and catch the IntegrityError.
    for _, row in df.iterrows():
        try:
            pd.DataFrame([row]).to_sql(name=table_name, con=conn, if_exists='append', index=False)
        except sqlite3.IntegrityError:
            logging.info(f"Skipping duplicate entry: {row.get('url')}")
        except Exception as e:
            logging.error(f"Failed to insert row into {table_name}. URL: {row.get('url')}. Error: {e}")
    conn.close()

# --- FLASK WEB APP ---
template_folder_path = resource_path('templates')
app = Flask(__name__, template_folder=template_folder_path)

@app.route('/')
def index():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT * FROM studies WHERE topic IS NOT NULL ORDER BY publication_date DESC, citations DESC")
    studies = c.fetchall()
    grouped_studies = defaultdict(list)
    for study in studies:
        topics = [topic.strip() for topic in study['topic'].split(',')]
        for topic in topics:
            grouped_studies[topic].append(study)

    c.execute("SELECT * FROM expert_opinions WHERE topic IS NOT NULL ORDER BY published_date DESC")
    opinions = c.fetchall()
    grouped_opinions = defaultdict(list)
    for opinion in opinions:
        topics = [topic.strip() for topic in opinion['topic'].split(',')]
        for topic in topics:
            grouped_opinions[topic].append(opinion)

    conn.close()
    
    all_topics = sorted(list(set(grouped_studies.keys()) | set(grouped_opinions.keys())))

    return render_template('index.html', all_topics=all_topics, grouped_studies=grouped_studies, grouped_opinions=grouped_opinions)

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
                request.form.get('citations', 0, type=int), request.form['study_type'], request.form['topic']
            ))
            conn.commit()
        except Exception as e:
            logging.error(f"Error adding manual study: {e}")
        finally:
            if conn:
                conn.close()
        return redirect(url_for('index'))
    return render_template('add_study.html')

def run_flask_app():
    """Runs the Flask web application and opens the browser."""
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000/")).start()
    app.run(debug=False, port=5000)

# --- WORKFLOW ORCHESTRATION ---
def main_workflow():
    """The main function that orchestrates the entire workflow."""
    print("--- Starting C. elegans Research Cataloging System ---")

    print("\n[1/5] Generating workflow diagram...")
    generate_workflow_diagram()

    print("\n[2/5] Setting up database...")
    setup_database()
    print("  - Database setup complete.")

    keywords = {
        'IGF-1 Signaling': '"Caenorhabditis elegans" "IGF-1 signaling"',
        'DAF-2/DAF-16 Pathway': '"C. elegans" ("DAF-2" OR "AGE-1" OR "DAF-16")',
        'Insulin & Longevity': '"C. elegans" insulin signaling longevity',
        'Aging & Longevity': '"C. elegans" (aging OR longevity)',
        'Neurodegeneration Models': '"C. elegans" (neurodegeneration OR "Alzheimer\'s" OR "Parkinson\'s")',
        'Immunity & Infection': '"C. elegans" (immunity OR infection OR pathogen)',
        'Cancer Models': '"C. elegans" ("cancer model" OR tumor OR apoptosis)',
        'Programmed Cell Death': '"C. elegans" ("programmed cell death" OR apoptosis OR "CED-3" OR "CED-4")',
        'RNAi Mechanism': '"C. elegans" (RNAi OR "RNA interference")',
        'Developmental Biology': '"C. elegans" (development OR "developmental biology" OR embryo)',
        'Stress Response': '"C. elegans" ("stress response" OR "heat shock" OR oxidative)',
        'Metabolism': '"C. elegans" (metabolism OR "lipid metabolism")',
        'Neuronal Development': '"C. elegans" ("neuronal development" OR "axon guidance")'
    }
    
    print(f"\n[3/5] Beginning large-scale data scraping for {len(keywords)} keyword sets.")
    print(">>> This may take a very long time (30-60+ minutes) on the first run. <<<")
    
    for topic, query in keywords.items():
        logging.info(f"--- Scraping for topic: '{topic}' ---")
        
        pubmed_df = scrape_pubmed(query, topic, max_results=1000)
        scholar_df = scrape_google_scholar(query, topic, max_results=1000)
        
        news_df = scrape_news(query, topic, max_results=100)
        twitter_df = scrape_twitter(query, topic, max_results=200)
        youtube_df = scrape_youtube(query, topic, max_results=100)

        all_studies_df = pd.concat([pubmed_df, scholar_df], ignore_index=True)
        all_opinions_df = pd.concat([news_df, twitter_df, youtube_df], ignore_index=True)

        print(f"\n[4/5] Storing data for topic '{topic}' into the database...")
        store_dataframe(all_studies_df, 'studies')
        store_dataframe(all_opinions_df, 'expert_opinions')
        print(f"  - Finished storing data for '{topic}'.")

    print("\n[5/5] All scraping complete. Launching web interface...")
    print(">>> Your research database is available at http://127.0.0.1:5000/ <<<")
    print(">>> A 'Workflow_Diagram.png' has been generated in this folder. <<<")
    print(">>> Close this terminal window to shut down the server. <<<")
    run_flask_app()

if __name__ == '__main__':
    # This allows the GitHub Actions workflow to generate the diagram as a build artifact
    # without running the entire data scraping process.
    if len(sys.argv) > 1 and sys.argv[1] == '--generate-diagram-only':
        print("Generating workflow diagram for build artifact...")
        generate_workflow_diagram()
        print("Diagram 'Workflow_Diagram.png' generated successfully.")
    else:
        main_workflow()
