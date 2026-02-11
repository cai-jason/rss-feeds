import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
from feedgen.feed import FeedGenerator
import time
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import setup_feed_links, get_feeds_dir, sort_posts_for_feed

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BLOG_URL = "https://openai.com/news/engineering/"
FEED_NAME = "openai_engineering"


def stable_fallback_date(identifier):
    """Generate a stable date from a URL or title hash."""
    hash_val = abs(hash(identifier)) % 730
    epoch = datetime(2023, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
    return epoch + timedelta(days=hash_val)


def setup_selenium_driver():
    """Set up Selenium WebDriver with undetected-chromedriver."""
    options = uc.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
    return uc.Chrome(options=options)


def fetch_news_content_selenium(url):
    """Fetch the fully loaded HTML content of a webpage using Selenium."""
    driver = None
    try:
        logger.info(f"Fetching content from URL: {url}")
        driver = setup_selenium_driver()
        driver.get(url)

        wait_time = 5
        logger.info(f"Waiting {wait_time} seconds for the page to fully load...")
        time.sleep(wait_time)

        html_content = driver.page_source
        logger.info("Successfully fetched HTML content")
        return html_content

    except Exception as e:
        logger.error(f"Error fetching content: {e}")
        raise
    finally:
        if driver:
            driver.quit()


def parse_openai_eng_html(html_content):
    """Parse the HTML content from OpenAI's Engineering News page."""
    soup = BeautifulSoup(html_content, "html.parser")
    articles = []
    seen_links = set()

    # Find article cards: <div class="group relative"> containing links to /index/
    cards = soup.select("div.group.relative")

    for card in cards:
        try:
            # Find the article link
            link_elem = card.select_one("a[href*='/index/']")
            if not link_elem:
                continue

            href = link_elem.get("href", "")
            if not href:
                continue

            # Build full URL
            if href.startswith("/"):
                link = "https://openai.com" + href
            elif href.startswith("http"):
                link = href
            else:
                continue

            # Deduplicate
            if link in seen_links:
                continue
            seen_links.add(link)

            # Extract title from the text-h5 div
            title_elem = card.select_one("div.text-h5")
            if not title_elem:
                continue
            title = title_elem.get_text(strip=True)
            if not title:
                continue

            # Extract date from <time> element
            time_elem = card.select_one("time[datetime]")
            if time_elem:
                datetime_str = time_elem.get("datetime", "")
                try:
                    date = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M")
                    date = date.replace(tzinfo=pytz.UTC)
                except ValueError:
                    try:
                        date = datetime.strptime(datetime_str, "%Y-%m-%d")
                        date = date.replace(tzinfo=pytz.UTC)
                    except ValueError:
                        logger.warning(
                            f"Date parsing failed for article: {title}"
                        )
                        date = stable_fallback_date(link)
            else:
                date = stable_fallback_date(link)

            # Extract category
            category_span = card.select_one("span.text-meta span:first-child")
            if not category_span:
                # Fallback: look for any span with category text
                meta_p = card.select_one("p.text-meta")
                if meta_p:
                    spans = meta_p.find_all("span", recursive=False)
                    category = spans[0].get_text(strip=True) if spans else "Engineering"
                else:
                    category = "Engineering"
            else:
                category = category_span.get_text(strip=True)

            articles.append(
                {
                    "title": title,
                    "link": link,
                    "date": date,
                    "category": category,
                    "description": title,
                }
            )
        except Exception as e:
            logger.warning(f"Skipping an article due to parsing error: {e}")
            continue

    logger.info(f"Parsed {len(articles)} articles")
    return articles


def generate_rss_feed(articles):
    """Generate RSS feed from parsed articles."""
    fg = FeedGenerator()
    fg.title("OpenAI Engineering News")
    fg.description(
        "Stories about the technology and builders at OpenAI."
    )
    setup_feed_links(fg, blog_url=BLOG_URL, feed_name=FEED_NAME)
    fg.language("en")

    sorted_articles = sort_posts_for_feed(articles)

    for article in sorted_articles:
        fe = fg.add_entry()
        fe.title(article["title"])
        fe.link(href=article["link"])
        fe.description(article["description"])
        fe.published(article["date"])
        fe.category(term=article["category"])

    logger.info("RSS feed generated successfully")
    return fg


def save_rss_feed(feed_generator):
    """Save RSS feed to an XML file."""
    feeds_dir = get_feeds_dir()
    output_file = feeds_dir / f"feed_{FEED_NAME}.xml"
    feed_generator.rss_file(str(output_file), pretty=True)
    logger.info(f"RSS feed saved to {output_file}")
    return output_file


def main():
    """Main function to generate OpenAI Engineering News RSS feed."""
    url = f"{BLOG_URL}?limit=500"

    try:
        html_content = fetch_news_content_selenium(url)
        articles = parse_openai_eng_html(html_content)
        if not articles:
            logger.warning("No articles were parsed. Check your selectors.")
        feed = generate_rss_feed(articles)
        save_rss_feed(feed)
    except Exception as e:
        logger.error(f"Failed to generate RSS feed: {e}")


if __name__ == "__main__":
    main()
