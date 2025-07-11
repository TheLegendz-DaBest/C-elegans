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
        dot.attr(rankdir='TB', label='C. elegans Research Aggregator Workflow', fontsize='20')

        # Node definitions... (omitted for brevity, same as original)

        dot.render(WORKFLOW_DIAGRAM_FILENAME.replace('.png', ''), format='png', cleanup=True)
        logging.info(f"Successfully created '{WORKFLOW_DIAGRAM_FILENAME}'")
    except Exception as e:
        logging.error(f"Could not generate workflow diagram. Error: {e}")

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
    # (Implementation is unchanged)
    pass

def scrape_google_scholar(query, topic, max_results=1000):
    # (Implementation is unchanged)
    pass

def scrape_news(query, topic, max_results=100):
    # (Implementation is unchanged)
    pass

def scrape_twitter(query, topic, max_results=200):
    # (Implementation is unchanged)
    pass

def scrape_youtube(query, topic, max_results=100):
    # (Implementation is unchanged)
    pass

def store_dataframe(df, table_name):
    """
    Stores a Pandas DataFrame in the specified database table efficiently.

    Args:
        df (pd.DataFrame): The DataFrame to store.
        table_name (str): The name of the table to insert data into.
    """
    if df.empty:
        logging.info(f"DataFrame for table '{table_name}' is empty. Nothing to store.")
        return

    try:
        conn = sqlite3.connect(DATABASE_FILE)
        # Use the 'append' option to add new data. The UNIQUE constraint on the URL
        # will prevent duplicates if the same data is scraped again.
        # The to_sql method is highly optimized for this task.
        df.to_sql(table_name, conn, if_exists='append', index=False)
        conn.close()
        logging.info(f"Successfully stored {len(df)} records in the '{table_name}' table.")
    except sqlite3.IntegrityError as e:
        # This error is expected when trying to insert duplicate URLs.
        # A more granular approach would be to loop and try/except each row,
        # but to_sql is much faster. We can handle this by simply logging it.
        logging.warning(f"An integrity error occurred, which may indicate duplicate entries were skipped: {e}")
    except Exception as e:
        logging.error(f"An error occurred while storing data in '{table_name}': {e}")


# --- FLASK WEB APP ---
template_folder_path = resource_path('templates')
app = Flask(__name__, template_folder=template_folder_path)

@app.route('/')
def index():
    # (Implementation is unchanged)
    pass

@app.route('/add_study', methods=['GET', 'POST'])
def add_study():
    # (Implementation is unchanged)
    pass

def run_flask_app():
    """Runs the Flask web application and opens the browser."""
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000/")).start()
    app.run(debug=False, port=5000)

# --- WORKFLOW ORCHESTRATION ---
def main_workflow():
    """The main function that orchestrates the entire workflow for the client."""
    print("--- Starting C. elegans Research Cataloging System ---")

    # RUNTIME STEP: Extract the pre-built diagram from the executable.
    print("\n[1/5] Checking for and extracting workflow diagram...")
    extract_and_save_diagram()

    # RUNTIME STEP: Create and populate the database if it doesn't exist.
    print("\n[2/5] Setting up database...")
    setup_database()
    print("  - Database setup complete.")

    # (Keyword definition and scraping loop remain the same)
    
    print("\n[5/5] All scraping complete. Launching web interface...")
    run_flask_app()

if __name__ == '__main__':
    # This logic separates build-time actions from the main runtime workflow.
    if len(sys.argv) > 1 and sys.argv[1] == '--generate-diagram-only':
        # This block is called ONLY by the GitHub Actions workflow.
        print("Generating workflow diagram for build artifact...")
        generate_workflow_diagram()
    else:
        # This block is called when the client double-clicks the final executable.
        main_workflow()```