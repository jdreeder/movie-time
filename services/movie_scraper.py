import cloudscraper
from bs4 import BeautifulSoup
from tmdbv3api import TMDb, Movie, Search
import re
import logging
import time
import random
from functools import wraps
from requests.exceptions import ConnectionError, Timeout


logger = logging.getLogger(__name__)


def rate_limit(min_delay=2.0, max_delay=5.0):
    """Decorator to add random delays between requests"""
    def decorator(func):
        last_call = {'time': 0}
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_call['time']
            delay = random.uniform(min_delay, max_delay)
            
            if elapsed < delay:
                sleep_time = delay - elapsed
                logger.debug(f"[RATE-LIMIT] Sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
            
            last_call['time'] = time.time()
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


class MovieScraper:
    def __init__(self, api_key, min_delay=2.0, max_delay=5.0):
        self.api_key = api_key
        self.tmdb = TMDb()
        self.tmdb.api_key = self.api_key
        self.movie = Movie()
        
        self.min_delay = min_delay
        self.max_delay = max_delay
        
        # Create cloudscraper instance with browser configuration
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            delay=10  # Initial delay for challenge solving
        )
        
        # Add session persistence (mimics real browser behavior)
        self.scraper.headers.update({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        logger.info(f"[INIT] Created cloudscraper instance with {min_delay}-{max_delay}s delays")
    
    @rate_limit(min_delay=2.0, max_delay=5.0)
    def normalize_letterboxd_url(self, url: str) -> str:
        logger.debug(f"[NORMALIZE] Starting normalization for URL: {url}")
        if "boxd.it" in url:
            try:
                logger.debug(f"[NORMALIZE] Detected shortened URL, resolving...")
                response = self.scraper.get(url, allow_redirects=True, timeout=30)
                logger.debug(f"[NORMALIZE] Resolution status code: {response.status_code}")
                if response.status_code == 200:
                    logger.debug(f"[NORMALIZE] ✅ Successfully resolved to: {response.url}")
                    return response.url 
                else:
                    logger.warning(f"[NORMALIZE] ❌ Failed to resolve URL: {url}. Status code: {response.status_code}")
                    return None
            except Exception as e:
                logger.error(f"[NORMALIZE] ❌ Exception while resolving URL: {e}")
                return None
        else:
            logger.debug(f"[NORMALIZE] URL is already in full format")
            return url
    
    @rate_limit(min_delay=2.0, max_delay=5.0)
    def extract_movie_details_from_letterboxd(self, url, retry_count=0, max_retries=3):
        logger.info(f"[EXTRACT] Starting extraction from URL: {url}")
        try:
            logger.debug(f"[EXTRACT] Making HTTP request via cloudscraper (attempt {retry_count + 1}/{max_retries + 1})...")
            
            # Try the request with retry logic for connection errors
            try:
                response = self.scraper.get(url, timeout=30)
            except (ConnectionError, Timeout) as conn_error:
                if retry_count < max_retries:
                    backoff_time = (2 ** retry_count) * random.uniform(2, 4)
                    logger.warning(
                        f"[EXTRACT] ⚠️ Connection error (attempt {retry_count + 1}). "
                        f"Retrying in {backoff_time:.2f}s... Error: {str(conn_error)[:100]}"
                    )
                    time.sleep(backoff_time)
                    return self.extract_movie_details_from_letterboxd(url, retry_count + 1, max_retries)
                else:
                    logger.error(f"[EXTRACT] ❌ Max retries exceeded for connection errors")
                    return None, None, None
            
            logger.debug(f"[EXTRACT] Response status code: {response.status_code}")
            
            if response.status_code == 429:
                if retry_count < max_retries:
                    backoff_time = (2 ** retry_count) * random.uniform(1, 3)
                    logger.warning(f"[EXTRACT] ⚠️ Rate limited (429). Backing off for {backoff_time:.2f} seconds...")
                    time.sleep(backoff_time)
                    return self.extract_movie_details_from_letterboxd(url, retry_count + 1, max_retries)
                else:
                    logger.error(f"[EXTRACT] ❌ Max retries exceeded for rate limiting")
                    return None, None
            
            if response.status_code != 200:
                logger.error(f"[EXTRACT] ❌ Non-200 status code: {response.status_code}")
                return None, None
                
            logger.info(f"[EXTRACT] ✅ Successfully fetched page content (bypassed Cloudflare)")
            
            soup = BeautifulSoup(response.text, 'html.parser')
            logger.debug(f"[EXTRACT] Parsed HTML with BeautifulSoup")

            # First try to get the information from metadata tags (most reliable)
            # First try to get the information from metadata tags (most reliable)
            logger.debug(f"[EXTRACT] Attempting Method 1: Meta tag extraction...")
            meta_title = soup.find('meta', property='og:title')
            if meta_title and meta_title.get('content'):
                meta_content = meta_title['content']
                logger.debug(f"[EXTRACT] Found meta title: '{meta_content}'")
                match = re.search(r'(.*?)\s*\((\d{4})\)', meta_content)
                if match:
                    title = match.group(1).strip()
                    year = match.group(2)
                    logger.info(f"[EXTRACT] ✅ Method 1 SUCCESS - Title: '{title}', Year: {year}")
                    return title, year
                else:
                    logger.debug(f"[EXTRACT] Meta title found but regex didn't match expected pattern")
            else:
                logger.debug(f"[EXTRACT] No og:title meta tag found")

            # Fallback to HTML structure
            logger.debug(f"[EXTRACT] Attempting Method 2: HTML structure parsing...")
            content_wrap = soup.find('div', class_='content-wrap')
            if not content_wrap:
                logger.warning("[EXTRACT] ❌ Failed to find 'content-wrap' div")
                all_divs = soup.find_all('div', limit=10)
                logger.debug(f"[EXTRACT] Sample div classes found: {[div.get('class') for div in all_divs if div.get('class')]}")
                return None, None

            logger.debug(f"[EXTRACT] Found content-wrap div")

            title_element = content_wrap.find('h1', class_='headline-1 primaryname')
            if title_element:
                logger.debug(f"[EXTRACT] Found title element")
                span_element = title_element.find('span', class_='name')
                title = span_element.get_text(strip=True) if span_element else title_element.get_text(strip=True)
                logger.debug(f"[EXTRACT] Extracted title: '{title}'")
            else:
                logger.warning(f"[EXTRACT] No title element found")
                title = None

            year_element = content_wrap.find('div', class_='releaseyear')
            if year_element:
                year_link = year_element.find('a')
                year = year_link.get_text(strip=True) if year_link else None
                logger.debug(f"[EXTRACT] Extracted year: {year}")
            else:
                logger.warning(f"[EXTRACT] No year element found")
                year = None

            if not title or not year:
                logger.error(f"[EXTRACT] ❌ Method 2 FAILED - Title: {title}, Year: {year}")
                return None, None

            logger.info(f"[EXTRACT] ✅ Method 2 SUCCESS - Title: '{title}', Year: {year}")
            return title, year
            
        except cloudscraper.exceptions.CloudflareChallengeError as e:
            logger.error(f"[EXTRACT] ❌ Cloudflare Challenge Failed: {e}")
            if retry_count < max_retries:
                backoff_time = (2 ** retry_count) * 5
                logger.warning(f"[EXTRACT] Retrying after {backoff_time}s backoff...")
                time.sleep(backoff_time)
                return self.extract_movie_details_from_letterboxd(url, retry_count + 1, max_retries)
            return None, None
        except Exception as e:
            logger.error(f"[EXTRACT] ❌ Unexpected error: {e}")
            logger.exception("Full traceback:")
            return None, None

    def get_movie_details_from_tmdb_by_title_and_year(self, title, year):
        logger.debug(f"[TMDB] Fetching movie details for title: '{title}', year: {year}")
        try:
            movie_id = self.search_tmdb_for_movie_id(title, year)
            if movie_id is None:
                logger.warning(f"[TMDB] ❌ No TMDB ID found for movie: '{title}', {year}")
                return None

            logger.debug(f"[TMDB] Fetching details for movie ID: {movie_id}")
            details = self.movie.details(movie_id)
            credits = self.movie.credits(movie_id)
            director = [crew_member for crew_member in credits['crew'] if crew_member['job'] == 'Director']
            
            director_name = director[0]['name'] if director else 'Unknown'
            image_url = f"https://image.tmdb.org/t/p/original{details['poster_path']}"
            backdrop_url = f"https://image.tmdb.org/t/p/original{details['backdrop_path']}"
            runtime = details.get('runtime', 'Unknown')
            budget = details.get('budget', 'Unknown')
            revenue = details.get('revenue', 'Unknown')
            overview = details.get('overview', 'No overview available')
            release_date = details.get('release_date', 'Unknown')

            logger.info(f"[TMDB] ✅ Successfully extracted TMDB details for '{title}'")
            return {
                'name': details['title'],
                'year': details['release_date'].split('-')[0],
                'director': director_name,
                'image_url': image_url,
                'backdrop_url': backdrop_url,
                'runtime': runtime,
                'budget': budget,
                'revenue': revenue,
                'overview': overview,
                'release_date': release_date,
            }
        except Exception as e:
            logger.error(f"[TMDB] ❌ Error fetching details: {e}")
            logger.exception("Full traceback:")
            return None

    def get_movie_details_from_url(self, url):
        logger.info(f"[MAIN] Getting movie details from URL: {url}")
        normalized_url = self.normalize_letterboxd_url(url)
        if not normalized_url:
            logger.error(f"[MAIN] ❌ Failed to normalize URL: {url}")
            raise ValueError(f"Invalid or inaccessible URL: {url}")
            
        if "letterboxd.com" in normalized_url:
            title, year = self.extract_movie_details_from_letterboxd(normalized_url)
            if not title or not year:
                error_msg = f"Failed to extract movie details from Letterboxd page: {normalized_url}"
                logger.error(f"[MAIN] ❌ {error_msg}")
                raise ValueError(error_msg)
                
            details = self.get_movie_details_from_tmdb_by_title_and_year(title, year)
            if not details:
                error_msg = f"Failed to find movie in TMDB: '{title}' ({year})"
                logger.error(f"[MAIN] ❌ {error_msg}")
                raise ValueError(error_msg)
                
            details['url'] = normalized_url
            logger.info(f"[MAIN] ✅ Successfully retrieved all details for '{title}'")
            return details
        else:
            error_msg = f"URL is not a Letterboxd movie page: {url}"
            logger.error(f"[MAIN] ❌ {error_msg}")
            raise ValueError(error_msg)

    def search_tmdb_for_movie_id(self, title, year):
        logger.debug(f"[TMDB-SEARCH] Searching for movie ID - Title: '{title}', Year: {year}")
        search = Search()
        results = search.movies({'query': title, 'year': year})
        
        if results:
            logger.info(f"[TMDB-SEARCH] ✅ Found TMDB ID for '{title}': {results[0]['id']}")
            return results[0]['id']
        else:
            logger.warning(f"[TMDB-SEARCH] ❌ No results found for '{title}' ({year})")
            return None
