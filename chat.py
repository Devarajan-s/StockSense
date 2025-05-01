import os
import time
import json
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
import pytz
import altair as alt
from concurrent.futures import ThreadPoolExecutor

# Set page configuration
st.set_page_config(
    page_title="StockSense: Quality News Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better UI
st.markdown("""
<style>
    .main {
        padding-top: 2rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #f0f2f6;
        padding: 10px 20px;
        border-radius: 4px 4px 0px 0px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #ffffff;
        border-top: 2px solid #ff4b4b;
    }
    .news-card {
        background-color: #f9f9f9;
        border-left: 4px solid #4CAF50;
        padding: 15px;
        margin-bottom: 10px;
        border-radius: 5px;
    }
    .header-img {
        display: block;
        margin-left: auto;
        margin-right: auto;
        width: 100px;
    }
    .stAlert {
        border-radius: 5px;
    }
    .small-text {
        font-size: 12px;
        color: #666;
    }
    .source-text {
        font-size: 11px;
        color: #888;
        text-transform: uppercase;
    }
    .timestamp {
        color: #888;
        font-size: 11px;
    }
    .sentiment-positive {
        color: #1E8449;
        font-weight: bold;
    }
    .sentiment-negative {
        color: #C0392B;
        font-weight: bold;
    }
    .sentiment-neutral {
        color: #7F8C8D;
        font-weight: bold;
    }
    .cta-button {
        background-color: #1E88E5;
        color: white;
        padding: 12px 20px;
        text-align: center;
        text-decoration: none;
        display: inline-block;
        font-size: 16px;
        margin: 4px 2px;
        border-radius: 4px;
        border: none;
        cursor: pointer;
    }
    .cta-button:hover {
        background-color: #1565C0;
    }
    .metric-container {
        background-color: #f9f9f9;
        padding: 15px;
        border-radius: 5px;
        text-align: center;
        margin-bottom: 10px;
    }
    .metric-value {
        font-size: 24px;
        font-weight: bold;
    }
    .metric-label {
        font-size: 14px;
        color: #666;
    }
</style>
""", unsafe_allow_html=True)

class StockNewsChatbot:
    def __init__(self):
        # API keys
        self.groq_api_key = "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"
        self.alpha_vantage_key = os.getenv("ALPHA_VANTAGE_KEY", "")
        self.finnhub_api_key = "d09km19r01qnv9cjjitgd09km19r01qnv9cjjiu0"
        self.polygon_api_key = "4pHn0mqKlNyZKsHHfbjt0SkHbkinNAyY"
        self.news_api_key = "d87e7a3095cd997cf9fcb566e00db619"
        
        # Cache for API responses
        self.cache = {}
        self.cache_expiry = {}
        self.cache_duration = timedelta(minutes=30)
        
        # Initialize session state for history
        if 'search_history' not in st.session_state:
            st.session_state.search_history = []
        if 'favorite_stocks' not in st.session_state:
            st.session_state.favorite_stocks = []
        if 'app_mode' not in st.session_state:
            st.session_state.app_mode = "news"  # news, analysis, history

    def _call_groq_api(self, prompt: str, max_retries: int = 3) -> str:
        """Call Groq API with robust error handling and retry mechanism.

        Args:
            prompt (str): Prompt to send to the API
            max_retries (int): Maximum number of retry attempts
        
        Returns:
            str: API response or error message
        """
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama3-8b-8192",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0.2
        }
        
        for i in range(max_retries):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=15)
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
                else:
                    st.warning(f"API attempt {i+1}/{max_retries} failed with status {resp.status_code}")
                    if i < max_retries - 1:
                        time.sleep(2 ** i)  # Exponential backoff
            except Exception as e:
                st.warning(f"API attempt {i+1}/{max_retries} failed: {str(e)}")
                if i < max_retries - 1:
                    time.sleep(2 ** i)
                    
        return "Failed to get a response from the AI service. Please try again later."

    def _call_groq_api_with_system(self, system_prompt: str, user_prompt: str, max_retries: int = 3) -> str:
        """Call Groq API with system prompt for more control.

        Args:
            system_prompt (str): System instructions
            user_prompt (str): User prompt
            max_retries (int): Maximum number of retry attempts
        
        Returns:
            str: API response or error message
        """
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama3-8b-8192",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 800,
            "temperature": 0.1
        }
        
        cache_key = f"{system_prompt}|{user_prompt}"
        if cache_key in self.cache and datetime.now() < self.cache_expiry.get(cache_key, datetime.min):
            return self.cache[cache_key]
        
        for i in range(max_retries):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=15)
                if resp.status_code == 200:
                    result = resp.json()["choices"][0]["message"]["content"].strip()
                    # Cache the result
                    self.cache[cache_key] = result
                    self.cache_expiry[cache_key] = datetime.now() + self.cache_duration
                    return result
                else:
                    if i < max_retries - 1:
                        time.sleep(2 ** i)
            except Exception as e:
                if i < max_retries - 1:
                    time.sleep(2 ** i)
                    
        return "Failed to get a response from the AI service. Please try again later."

    def fetch_news_multi_source(self, symbol: str, company_name: str = "") -> list:
        """
        Fetch news from multiple sources for more comprehensive coverage
        """
        all_articles = []
        
        # Try to use cache if available
        cache_key = f"news_{symbol}"
        if cache_key in self.cache and datetime.now() < self.cache_expiry.get(cache_key, datetime.min):
            return self.cache[cache_key]
        
        search_terms = [symbol]
        if company_name:
            search_terms.append(company_name)
            
        # Alpha Vantage News (if key available)
        if self.alpha_vantage_key:
            try:
                url = f"https://www.alphavantage.co/query"
                params = {
                    "function": "NEWS_SENTIMENT",
                    "tickers": symbol,
                    "apikey": self.alpha_vantage_key,
                    "limit": 25
                }
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "feed" in data:
                        for article in data["feed"]:
                            all_articles.append({
                                "title": article.get("title", ""),
                                "url": article.get("url", ""),
                                "source": article.get("source", "Alpha Vantage"),
                                "published_at": article.get("time_published", ""),
                                "summary": article.get("summary", ""),
                                "sentiment": article.get("overall_sentiment_score", 0)
                            })
            except Exception as e:
                pass
                
        # Finnhub News (if key available)
        if self.finnhub_api_key:
            try:
                finnhub_url = f"https://finnhub.io/api/v1/company-news"
                yesterday = datetime.now() - timedelta(days=7)
                today = datetime.now()
                params = {
                    "symbol": symbol,
                    "from": yesterday.strftime("%Y-%m-%d"),
                    "to": today.strftime("%Y-%m-%d"),
                    "token": self.finnhub_api_key
                }
                response = requests.get(finnhub_url, params=params, timeout=10)
                if response.status_code == 200:
                    articles = response.json()
                    for article in articles[:20]:  # Limit to 20 most recent
                        all_articles.append({
                            "title": article.get("headline", ""),
                            "url": article.get("url", ""),
                            "source": article.get("source", "Finnhub"),
                            "published_at": datetime.fromtimestamp(article.get("datetime", 0)),
                            "summary": article.get("summary", ""),
                            "sentiment": 0  # Finnhub doesn't provide sentiment
                        })
            except Exception as e:
                pass
                
        # Polygon.io News (if key available)
        if self.polygon_api_key:
            try:
                polygon_url = f"https://api.polygon.io/v2/reference/news"
                params = {
                    "ticker": symbol,
                    "apiKey": self.polygon_api_key,
                    "limit": 20
                }
                response = requests.get(polygon_url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "results" in data:
                        for article in data["results"]:
                            all_articles.append({
                                "title": article.get("title", ""),
                                "url": article.get("article_url", ""),
                                "source": article.get("publisher", {}).get("name", "Polygon.io"),
                                "published_at": article.get("published_utc", ""),
                                "summary": article.get("description", ""),
                                "sentiment": 0  # Polygon doesn't provide sentiment
                            })
            except Exception as e:
                pass

        # News API (fallback)
        if self.news_api_key:
            for term in search_terms:
                try:
                    news_url =  "https://gnews.io/api/v4/search"
                    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
                    params = {
                        "q": term,
                        "from": week_ago,
                        "sortBy": "publishedAt",
                        "language": "en",
                        "apiKey": self.news_api_key,
                        "pageSize": 15
                    }
                    response = requests.get(news_url, params=params, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("articles"):
                            for article in data["articles"]:
                                all_articles.append({
                                    "title": article.get("title", ""),
                                    "url": article.get("url", ""),
                                    "source": article.get("source", {}).get("name", "News API"),
                                    "published_at": article.get("publishedAt", ""),
                                    "summary": article.get("description", ""),
                                    "sentiment": 0  # News API doesn't provide sentiment
                                })
                except Exception as e:
                    pass
        
        # Fallback to a free news API if we still don't have articles
        if not all_articles:
            try:
                gnews_url = "https://gnews.io/api/v4/search"
                params = {
                    "q": f"{symbol} stock",
                    "token": "d87e7a3095cd997cf9fcb566e00db619",  # Backup API key
                    "lang": "en",
                    "max": 20
                }
                response = requests.get(gnews_url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "articles" in data:
                        for article in data["articles"]:
                            all_articles.append({
                                "title": article.get("title", ""),
                                "url": article.get("url", ""),
                                "source": article.get("source", {}).get("name", "GNews"),
                                "published_at": article.get("publishedAt", ""),
                                "summary": article.get("description", ""),
                                "sentiment": 0
                            })
            except Exception as e:
                pass
                
        # Remove duplicates by URL
        seen_urls = set()
        unique_articles = []
        for article in all_articles:
            if article["url"] not in seen_urls:
                seen_urls.add(article["url"])
                unique_articles.append(article)
        
        # Cache the results
        self.cache[cache_key] = unique_articles
        self.cache_expiry[cache_key] = datetime.now() + self.cache_duration
        
        return unique_articles

    def get_company_info(self, symbol: str) -> dict:
        """Get company information for a given stock symbol"""
        cache_key = f"company_{symbol}"
        if cache_key in self.cache and datetime.now() < self.cache_expiry.get(cache_key, datetime.min):
            return self.cache[cache_key]
            
        company_info = {
            "name": "",
            "sector": "",
            "industry": "",
            "description": "",
            "exchange": "",
            "website": "",
            "market_cap": "",
        }
            
        # Try Alpha Vantage first
        if self.alpha_vantage_key:
            try:
                url = f"https://www.alphavantage.co/query"
                params = {
                    "function": "OVERVIEW",
                    "symbol": symbol,
                    "apikey": self.alpha_vantage_key
                }
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "Name" in data:
                        company_info["name"] = data.get("Name", "")
                        company_info["sector"] = data.get("Sector", "")
                        company_info["industry"] = data.get("Industry", "")
                        company_info["description"] = data.get("Description", "")
                        company_info["exchange"] = data.get("Exchange", "")
                        company_info["market_cap"] = data.get("MarketCapitalization", "")
                        
                        # Cache the result
                        self.cache[cache_key] = company_info
                        self.cache_expiry[cache_key] = datetime.now() + timedelta(days=7)  # Company info changes less frequently
                        return company_info
            except Exception as e:
                pass
        
        # Try Finnhub as a backup
        if self.finnhub_api_key:
            try:
                url = f"https://finnhub.io/api/v1/stock/profile2"
                params = {
                    "symbol": symbol,
                    "token": self.finnhub_api_key
                }
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "name" in data:
                        company_info["name"] = data.get("name", "")
                        company_info["sector"] = data.get("finnhubIndustry", "")
                        company_info["industry"] = data.get("finnhubIndustry", "")
                        company_info["description"] = ""  # Finnhub doesn't provide this
                        company_info["exchange"] = data.get("exchange", "")
                        company_info["market_cap"] = data.get("marketCapitalization", "")
                        company_info["website"] = data.get("weburl", "")
                        
                        # Cache the result
                        self.cache[cache_key] = company_info
                        self.cache_expiry[cache_key] = datetime.now() + timedelta(days=7)
                        return company_info
            except Exception as e:
                pass
                
        # If we still don't have the company name, use the symbol
        if not company_info["name"]:
            company_info["name"] = symbol
        
        # Cache the result even if it's partial
        self.cache[cache_key] = company_info
        self.cache_expiry[cache_key] = datetime.now() + timedelta(days=1)
        return company_info

    def get_stock_data(self, symbol: str) -> dict:
        """Get stock price data for the given symbol"""
        cache_key = f"stock_{symbol}"
        if cache_key in self.cache and datetime.now() < self.cache_expiry.get(cache_key, datetime.min):
            return self.cache[cache_key]
            
        stock_data = {
            "current_price": None,
            "change": None,
            "change_percent": None,
            "open": None,
            "high": None,
            "low": None,
            "volume": None,
            "previous_close": None,
            "history": []
        }
        
        # Try Alpha Vantage
        if self.alpha_vantage_key:
            try:
                # Get intraday data
                url = f"https://www.alphavantage.co/query"
                params = {
                    "function": "TIME_SERIES_INTRADAY",
                    "symbol": symbol,
                    "interval": "5min",
                    "apikey": self.alpha_vantage_key,
                    "outputsize": "compact"
                }
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    time_series = data.get("Time Series (5min)", {})
                    if time_series:
                        # Get the latest data point
                        latest_timestamp = max(time_series.keys())
                        latest_data = time_series[latest_timestamp]
                        
                        stock_data["current_price"] = float(latest_data.get("4. close", 0))
                        stock_data["open"] = float(latest_data.get("1. open", 0))
                        stock_data["high"] = float(latest_data.get("2. high", 0))
                        stock_data["low"] = float(latest_data.get("3. low", 0))
                        stock_data["volume"] = int(latest_data.get("5. volume", 0))
                        
                        # Get daily data for previous close
                        params["function"] = "TIME_SERIES_DAILY"
                        params.pop("interval")
                        response = requests.get(url, params=params, timeout=10)
                        if response.status_code == 200:
                            daily_data = response.json().get("Time Series (Daily)", {})
                            if daily_data:
                                daily_timestamps = sorted(daily_data.keys(), reverse=True)
                                if len(daily_timestamps) > 1:
                                    prev_day = daily_timestamps[1]
                                    stock_data["previous_close"] = float(daily_data[prev_day].get("4. close", 0))
                                    
                                    # Calculate change and change percent
                                    stock_data["change"] = stock_data["current_price"] - stock_data["previous_close"]
                                    if stock_data["previous_close"] > 0:
                                        stock_data["change_percent"] = (stock_data["change"] / stock_data["previous_close"]) * 100
                                        
                                # Get historical data for chart
                                for timestamp in daily_timestamps[:30]:  # Last 30 days
                                    stock_data["history"].append({
                                        "date": timestamp,
                                        "close": float(daily_data[timestamp].get("4. close", 0))
                                    })
                            
                        # Cache the result
                        self.cache[cache_key] = stock_data
                        self.cache_expiry[cache_key] = datetime.now() + timedelta(minutes=15)
                        return stock_data
            except Exception as e:
                pass
                
        # Try Finnhub as a backup
        if self.finnhub_api_key:
            try:
                # Get quote
                url = f"https://finnhub.io/api/v1/quote"
                params = {
                    "symbol": symbol,
                    "token": self.finnhub_api_key
                }
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "c" in data:
                        stock_data["current_price"] = data.get("c", 0)
                        stock_data["open"] = data.get("o", 0)
                        stock_data["high"] = data.get("h", 0)
                        stock_data["low"] = data.get("l", 0)
                        stock_data["previous_close"] = data.get("pc", 0)
                        stock_data["change"] = stock_data["current_price"] - stock_data["previous_close"]
                        if stock_data["previous_close"] > 0:
                            stock_data["change_percent"] = (stock_data["change"] / stock_data["previous_close"]) * 100
                            
                        # Get historical data
                        today = datetime.now()
                        month_ago = today - timedelta(days=30)
                        url = f"https://finnhub.io/api/v1/stock/candle"
                        params = {
                            "symbol": symbol,
                            "resolution": "D",
                            "from": int(month_ago.timestamp()),
                            "to": int(today.timestamp()),
                            "token": self.finnhub_api_key
                        }
                        response = requests.get(url, params=params, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("s") == "ok":
                                timestamps = data.get("t", [])
                                closes = data.get("c", [])
                                for i in range(len(timestamps)):
                                    date_str = datetime.fromtimestamp(timestamps[i]).strftime("%Y-%m-%d")
                                    stock_data["history"].append({
                                        "date": date_str,
                                        "close": closes[i]
                                    })
                        
                        # Cache the result
                        self.cache[cache_key] = stock_data
                        self.cache_expiry[cache_key] = datetime.now() + timedelta(minutes=15)
                        return stock_data
            except Exception as e:
                pass
                
        # If we still don't have data, return what we have
        self.cache[cache_key] = stock_data
        self.cache_expiry[cache_key] = datetime.now() + timedelta(minutes=15)
        return stock_data

    def filter_quality_news(self, articles: list) -> list:
        """
        Filter out general news and keep only quality/important financial news
        """
        if not articles:
            return []
            
        # Extract just the titles for filtering
        headlines = [f"- {article['title']}" for article in articles]
        
        # Build the prompt for the Groq API
        system_prompt = """
        You are a financial news expert specializing in stock market coverage.
        Your task is to identify HIGH-QUALITY financial news that is IMPORTANT for investors.

        Quality financial news:
        - Contains specific financial data, metrics, or business developments
        - Discusses earnings reports, revenue figures, or profit/loss information
        - Covers mergers, acquisitions, partnerships, or major business deals
        - Reports on product launches, market expansion, or strategic pivots
        - Mentions regulatory developments or legal issues affecting the company
        - Includes analyst ratings, price targets, or market forecasts
        - Discusses industry trends directly impacting the company

        General news to EXCLUDE:
        - Vague or general market commentary without specific insights
        - Opinion pieces without substantive financial information
        - General economic news not directly tied to the specific company
        - Basic PR or promotional content without meaningful data
        - News that merely restates already known information
        
        Return ONLY the numbers (indexes) of the articles that qualify as high-quality financial news,
        formatted as a comma-separated list. For example: 1,3,7,12
        
        If none of the articles qualify, return "0".
        """
        
        user_prompt = f"Here are {len(headlines)} financial news headlines to evaluate. Return only the indices of high-quality news:\n\n"
        for i, headline in enumerate(headlines, 1):
            user_prompt += f"{i}. {headline.strip('- ')}\n"
            
        # Get response from Groq
        response = self._call_groq_api_with_system(system_prompt, user_prompt)
        
        # Process the response
        try:
            # Handle the case where no articles qualify
            if response.strip() == "0":
                return []
                
            # Parse the list of indices
            indices = []
            for part in response.split(','):
                part = part.strip()
                if part.isdigit():
                    indices.append(int(part))
                    
            # Validate indices
            valid_indices = [i for i in indices if 1 <= i <= len(articles)]
            
            # Return filtered articles
            return [articles[i-1] for i in valid_indices]
        except Exception as e:
            # If there's an error in parsing, just return the original list
            return articles

    def analyze_news_sentiment(self, articles: list) -> float:
        """Analyze the sentiment of news articles if not already available"""
        if not articles:
            return 0
            
        # Count articles with existing sentiment scores
        articles_with_sentiment = [a for a in articles if a.get("sentiment") != 0]
        
        # If we already have sentiment for most articles, calculate average
        if len(articles_with_sentiment) >= len(articles) * 0.5:
            return sum(a["sentiment"] for a in articles_with_sentiment) / len(articles_with_sentiment)
            
        # Otherwise, use Groq to analyze sentiment
        system_prompt = """
        You are a financial sentiment analysis expert. Analyze the sentiment of financial news headlines 
        about a specific stock or company. Rate each headline on a scale from -1.0 (extremely negative) 
        to +1.0 (extremely positive), where 0.0 is neutral.
        
        Return your analysis as a single number representing the average sentiment score.
        """
        
        user_prompt = "Analyze the sentiment of these financial news headlines:\n\n"
        for article in articles:
            user_prompt += f"- {article['title']}\n"
            
        # Get response from Groq
        response = self._call_groq_api_with_system(system_prompt, user_prompt)
        
        # Try to extract a number from the response
        try:
            # Look for a number pattern in the response
            import re
            numbers = re.findall(r"[-+]?[0-9]*\.?[0-9]+", response)
            if numbers:
                sentiment = float(numbers[0])
                # Ensure it's within the -1 to 1 range
                return max(-1.0, min(1.0, sentiment))
        except:
            pass
            
        return 0  # Default to neutral if we can't parse a sentiment score

    def generate_news_summary(self, symbol: str, company_name: str, articles: list) -> str:
        """Generate a summary of the key news and insights for the stock"""
        if not articles:
            return "No quality news found for this stock."
            
        cache_key = f"summary_{symbol}_{len(articles)}"
        if cache_key in self.cache and datetime.now() < self.cache_expiry.get(cache_key, datetime.min):
            return self.cache[cache_key]
            
        # Get news content
        news_content = ""
        for i, article in enumerate(articles[:10], 1):  # Limit to top 10 articles
            news_content += f"Article {i}: {article['title']}\n"
            if article.get('summary'):
                news_content += f"Summary: {article['summary']}\n\n"
            else:
                news_content += "\n"
                
        system_prompt = """
        You are a financial analyst specializing in stock market news analysis. 
        Generate a concise, informative summary of the key news for a specific stock.
        
        Your summary should:
        1. Identify the most important developments affecting the stock
        2. Highlight key financial metrics or business changes mentioned
        3. Note any analyst opinions or price target changes
        4. Mention any major events (earnings, acquisitions, etc.)
        
        Be factual and precise. Include specific numbers and data points when available.
        Avoid generic language and speculation. End with a one-sentence market outlook.
        
        Format your response using markdown for better readability, with headings and bullet points.
        Keep your response under 400 words.
        """
        
        user_prompt = f"""Generate a concise financial news summary for {company_name} ({symbol}) based on these recent news items:

{news_content}
"""
        
        # Get response from Groq
        response = self._call_groq_api_with_system(system_prompt, user_prompt)
        
        # Cache the result
        self.cache[cache_key] = response
        self.cache_expiry[cache_key] = datetime.now() + self.cache_duration
        
        return response

    def generate_investment_analysis(self, symbol: str, company_info: dict, stock_data: dict, articles: list) -> str:
        """Generate an AI-powered investment analysis for the stock"""
        if not articles or not stock_data["current_price"]:
            return "Insufficient data available for investment analysis."
            
        cache_key = f"analysis_{symbol}_{len(articles)}"
        if cache_key in self.cache and datetime.now() < self.cache_expiry.get(cache_key, datetime.min):
            return self.cache[cache_key]
            
        # Extract key metrics for analysis
        company_name = company_info.get("name", symbol)
        sector = company_info.get("sector", "Unknown")
        current_price = stock_data.get("current_price", "N/A")
        change_percent = stock_data.get("change_percent", "N/A")
        
        # Get news titles for analysis
        news_content = "\n".join([f"- {article['title']}" for article in articles[:15]])
            
        system_prompt = """
        You are a professional stock analyst with expertise in financial markets.
        Create a concise but comprehensive investment analysis for a specific stock
        based on recent news and price data.
        
        Your analysis should include:
        1. Key Points: 2-3 bullet points highlighting the most important recent developments
        2. Strengths & Risks: 2-3 bullet points for each
        3. Outlook: A brief 1-2 sentence outlook on near-term prospects
        4. Conclusion: Whether investors should consider buying, holding, or selling
        
        Be specific and refer to actual news items and data points.
        Format your response in markdown for readability.
        Do not speculate beyond what the data supports.
        Do not make definitive price predictions or give financial advice.
        Keep your analysis under 500 words total.
        """
        
        user_prompt = f"""Create an investment analysis for {company_name} ({symbol}) in the {sector} sector.

Current price: ${current_price}
Recent price change: {change_percent}%

Recent News:
{news_content}
"""
        
        # Get response from Groq
        response = self._call_groq_api_with_system(system_prompt, user_prompt)
        
        # Cache the result
        self.cache[cache_key] = response
        self.cache_expiry[cache_key] = datetime.now() + self.cache_duration
        
        return response

    def add_to_history(self, symbol: str, company_name: str = ""):
        """Add a stock to the search history"""
        # Check if already in history
        for item in st.session_state.search_history:
            if item["symbol"] == symbol:
                # Move to top of history
                st.session_state.search_history.remove(item)
                st.session_state.search_history.insert(0, item)
                return
                
        # Add new item to history
        st.session_state.search_history.insert(0, {
            "symbol": symbol,
            "name": company_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        
        # Keep only the last 10 searches
        if len(st.session_state.search_history) > 10:
            st.session_state.search_history = st.session_state.search_history[:10]

    def toggle_favorite(self, symbol: str, company_name: str = ""):
        """Add or remove a stock from favorites"""
        # Check if already in favorites
        for item in st.session_state.favorite_stocks:
            if item["symbol"] == symbol:
                # Remove from favorites
                st.session_state.favorite_stocks.remove(item)
                return False
                
        # Add to favorites
        st.session_state.favorite_stocks.append({
            "symbol": symbol,
            "name": company_name,
            "added_on": datetime.now().strftime("%Y-%m-%d")
        })
        return True

    def is_favorite(self, symbol: str) -> bool:
        """Check if a stock is in favorites"""
        for item in st.session_state.favorite_stocks:
            if item["symbol"] == symbol:
                return True
        return False

    # Add this import to the top of your file:
# import altair as alt

    def render_stock_chart(self, stock_data: dict):
        """Render a stock price chart using Altair for better styling"""
        if not stock_data["history"]:
            st.info("No historical data available for chart")
            return
        
    # Convert to dataframe
        df = pd.DataFrame(stock_data["history"])
    
    # Convert date strings to datetime
        df["date"] = pd.to_datetime(df["date"])
    
    # Create the base chart
        base = alt.Chart(df).encode(
            x=alt.X('date:T', axis=alt.Axis(title=None, labelAngle=-45, format='%b %d')),
            y=alt.Y('close:Q', axis=alt.Axis(title='Price', format='$,.2f'))
        ).properties(
            title='Price History (30 Days)',
            height=300
        )
    
    # Create the line
        line = base.mark_line(color='#1E88E5').encode(
            tooltip=[
                alt.Tooltip('date:T', title='Date', format='%Y-%m-%d'),
                alt.Tooltip('close:Q', title='Price', format='$,.2f')
            ]
        )
    
    # Create points
        points = base.mark_circle(color='#1E88E5', size=50).encode(
            opacity=alt.condition(
                alt.datum.date == df['date'].max(),  # Highlight the last point
                alt.value(1),
                alt.value(0)  # Make other points transparent
            )
        )
    
    # Create the area underneath
        area = base.mark_area(color='#1E88E5', opacity=0.1).encode()
    
    # Combine the layers
        chart = (area + line + points).configure_view(
            strokeWidth=0
        ).configure_axisX(
            grid=False
        ).configure_axisY(
            grid=True,
            gridDash=[5, 5]
        ).interactive()
    
    # Display the chart
        st.altair_chart(chart, use_container_width=True)

    def run(self):
        """Run the main application"""
        # Sidebar
        with st.sidebar:
            st.image("https://img.icons8.com/color/96/null/stocks.png", width=80)
            st.title("StockSense")
            st.write("Your AI-powered stock news analyst")
            
            # Mode selection
            st.subheader("Navigation")
            selected_mode = st.radio(
                "Choose mode:",
                ["📰 News Finder", "📊 Analysis", "⭐ Favorites", "📜 History"],
                key="mode_selector"
            )
            st.session_state.app_mode = selected_mode.split()[1].lower()
            
            st.markdown("---")
            
            # API key management
            st.subheader("API Keys (Optional)")
            with st.expander("Configure keys"):
                st.text_input("Groq API Key", value=os.getenv("GROQ_API_KEY", ""), key="groq_key", type="password")
                st.text_input("Alpha Vantage API Key", value=os.getenv("ALPHA_VANTAGE_KEY", ""), key="alpha_key", type="password")
                st.text_input("Finnhub API Key", value=os.getenv("FINNHUB_API_KEY", ""), key="finnhub_key", type="password")
                st.text_input("News API Key", value=os.getenv("NEWS_API_KEY", ""), key="news_key", type="password")
                
                if st.button("Save Keys"):
                    os.environ["GROQ_API_KEY"] = st.session_state.groq_key
                    os.environ["ALPHA_VANTAGE_KEY"] = st.session_state.alpha_key
                    os.environ["FINNHUB_API_KEY"] = st.session_state.finnhub_key
                    os.environ["NEWS_API_KEY"] = st.session_state.news_key
                    self.groq_api_key = st.session_state.groq_key
                    self.alpha_vantage_key = st.session_state.alpha_key
                    self.finnhub_api_key = st.session_state.finnhub_key
                    self.news_api_key = st.session_state.news_key
                    st.success("API keys updated!")
            
            st.markdown("---")
            st.write("Made with ❤️ by [Your Name]")
        
        # Main content area
        if st.session_state.app_mode == "news":
            self.render_news_finder()
        elif st.session_state.app_mode == "analysis":
            self.render_analysis_mode()
        elif st.session_state.app_mode == "favorites":
            self.render_favorites()
        elif st.session_state.app_mode == "history":
            self.render_history()

    def render_news_finder(self):
        """Render the news finder interface"""
        st.title("📰 Quality Stock News Finder")
        st.write("Search for high-quality, actionable news about any stock")
        
        # Search box
        col1, col2 = st.columns([3, 1])
        with col1:
            symbol = st.text_input("Enter ticker symbol (e.g., AAPL, MSFT, TSLA)", key="news_symbol").strip().upper()
        with col2:
            search_clicked = st.button("Find News", type="primary", use_container_width=True)
            
        # Process search
        if search_clicked and symbol:
            self.process_stock_search(symbol)
        
        # Show some example stocks
        if not symbol and not search_clicked:
            st.write("### Try popular stocks")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if st.button("AAPL"):
                    self.process_stock_search("AAPL")
            with col2:
                if st.button("MSFT"):
                    self.process_stock_search("MSFT")
            with col3:
                if st.button("TSLA"):
                    self.process_stock_search("TSLA")
            with col4:
                if st.button("NVDA"):
                    self.process_stock_search("NVDA")

    def render_analysis_mode(self):
        """Render the stock analysis interface"""
        st.title("📊 Stock Analysis")
        st.write("Get AI-powered investment analysis")
        
        # Search box
        col1, col2 = st.columns([3, 1])
        with col1:
            symbol = st.text_input("Enter ticker symbol (e.g., AAPL, MSFT, TSLA)", key="analysis_symbol").strip().upper()
        with col2:
            search_clicked = st.button("Analyze", type="primary", use_container_width=True)
            
        # Process search
        if search_clicked and symbol:
            self.process_stock_search(symbol, mode="analysis")
            
        # Example stocks
        if not symbol and not search_clicked:
            st.write("### Try popular stocks")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if st.button("META"):
                    self.process_stock_search("META", mode="analysis")
            with col2:
                if st.button("AMZN"):
                    self.process_stock_search("AMZN", mode="analysis")
            with col3:
                if st.button("GOOG"):
                    self.process_stock_search("GOOG", mode="analysis")
            with col4:
                if st.button("JPM"):
                    self.process_stock_search("JPM", mode="analysis")

    def render_favorites(self):
        """Render the favorites interface"""
        st.title("⭐ Favorite Stocks")
        
        if not st.session_state.favorite_stocks:
            st.write("You haven't added any favorite stocks yet.")
            st.write("Search for a stock and click the star icon to add it to your favorites.")
            return
            
        # Display favorites
        for i, item in enumerate(st.session_state.favorite_stocks):
            symbol = item["symbol"]
            name = item["name"] or symbol
            col1, col2 = st.columns([5, 1])
            
            with col1:
                if st.button(f"{symbol} - {name}", key=f"fav_{i}", use_container_width=True):
                    self.process_stock_search(symbol)
            with col2:
                if st.button("❌", key=f"remove_{i}"):
                    self.toggle_favorite(symbol)
                    st.experimental_rerun()

    def render_history(self):
        """Render the search history interface"""
        st.title("📜 Search History")
        
        if not st.session_state.search_history:
            st.write("Your search history is empty.")
            return
            
        # Display search history
        for i, item in enumerate(st.session_state.search_history):
            symbol = item["symbol"]
            name = item["name"] or symbol
            timestamp = item["timestamp"]
            
            col1, col2 = st.columns([5, 1])
            with col1:
                if st.button(f"{symbol} - {name} ({timestamp})", key=f"hist_{i}", use_container_width=True):
                    self.process_stock_search(symbol)
            with col2:
                if st.button("❌", key=f"remove_hist_{i}"):
                    st.session_state.search_history.remove(item)
                    st.experimental_rerun()
                    
        if st.button("Clear All History"):
            st.session_state.search_history = []
            st.experimental_rerun()

    def process_stock_search(self, symbol: str, mode: str = None):
        """Process a stock search and display results"""
        if not mode:
            mode = st.session_state.app_mode
            
        with st.spinner(f"Searching for {symbol}..."):
            # Get company information
            company_info = self.get_company_info(symbol)
            company_name = company_info.get("name", symbol)
            
            # Add to search history
            self.add_to_history(symbol, company_name)
            
            # Get stock data
            stock_data = self.get_stock_data(symbol)
            
            # Get news articles
            articles = self.fetch_news_multi_source(symbol, company_name)
            
            # Filter for quality news
            quality_articles = self.filter_quality_news(articles)
            
            # Display company header
            self.display_company_header(symbol, company_info, stock_data)
            
            # Display results based on mode
            if mode == "news":
                self.display_news_results(symbol, company_name, quality_articles, articles)
            elif mode == "analysis":
                self.display_analysis_results(symbol, company_info, stock_data, quality_articles)
            else:
                self.display_news_results(symbol, company_name, quality_articles, articles)

    def display_company_header(self, symbol: str, company_info: dict, stock_data: dict):
        """Display company information header"""
        # Create a row for company name and favorite button
        header_cols = st.columns([9, 1])
    
        company_name = company_info.get("name", symbol)
        favorite = self.is_favorite(symbol)
        favorite_icon = "⭐" if favorite else "☆"
    
    # Display company name in first column
        with header_cols[0]:
            st.subheader(f"{company_name} ({symbol})")
    
    # Display favorite button in second column
        with header_cols[1]:
            if st.button(favorite_icon, key=f"fav_btn_{symbol}"):
                self.toggle_favorite(symbol, company_name)
                st.experimental_rerun()
    
    # Company metadata
        if company_info.get("sector"):
            st.caption(f"Sector: {company_info.get('sector')} | Industry: {company_info.get('industry', 'N/A')}")
    
    # Price information in separate row
        metric_cols = st.columns([2, 1, 1, 1])
    
        with metric_cols[1]:
            if stock_data.get("current_price"):
                st.metric(
                    "Price",
                    f"${stock_data['current_price']:.2f}",
                    f"{stock_data.get('change_percent', 0):.2f}%" if stock_data.get("change_percent") else None
                )
    
        with metric_cols[2]:
            if stock_data.get("open"):
                st.metric("Day Range", f"${stock_data.get('low', 0):.2f} - ${stock_data.get('high', 0):.2f}")
    
        with metric_cols[3]:
            if stock_data.get("volume"):
                volume_str = f"{stock_data.get('volume')/1000000:.1f}M" if stock_data.get('volume', 0) > 0 else "N/A"
                st.metric("Volume", volume_str)
            
    # Display chart if we have history
        if stock_data.get("history"):
            self.render_stock_chart(stock_data)
        
    # Company description
        if company_info.get("description"):
            with st.expander("Company Overview"):
                st.write(company_info.get("description"))
            
                if company_info.get("website"):
                    st.write(f"Website: [{company_info.get('website')}]({company_info.get('website')})")

    def display_news_results(self, symbol: str, company_name: str, quality_articles: list, all_articles: list):
        """Display news results"""
    # Create tabs for different views
        tabs = st.tabs(["📋 Quality News", "📊 Summary", "📰 All News"])
    
    # Quality News tab
        with tabs[0]:
            if not quality_articles:
                st.info(f"No quality news found for {symbol}. Try another ticker.")
            else:
                st.success(f"Found {len(quality_articles)} quality news items for {symbol}")
            
            # Display quality news
                for article in quality_articles:
                    with st.container():
                        # Get title preview (first 40 characters)
                        title_preview = article['title'][:40] + "..." if len(article['title']) > 40 else article['title']
                    
                        st.markdown(f"""
                        <div class="news-card">
                            <h4>{article['title']}</h4>
                            <p class="source-text">{article['source']} • {self.format_date(article['published_at'])}</p>
                            <p>{article.get('summary', '')[:200]}...</p>
                            <a href="{article['url']}" target="_blank">Read more: {title_preview}</a>
                        </div>
                        """, unsafe_allow_html=True)
    
    # Summary tab
        with tabs[1]:
            if not quality_articles:
                st.info(f"No quality news found to summarize for {symbol}.")
            else:
                with st.spinner("Generating summary of key insights..."):
                    summary = self.generate_news_summary(symbol, company_name, quality_articles)
                    st.markdown(summary)
                
            # Calculate and display sentiment
                sentiment = self.analyze_news_sentiment(quality_articles)
                sentiment_text = "Neutral"
                sentiment_class = "sentiment-neutral"
            
                if sentiment > 0.2:
                    sentiment_text = "Positive"
                    sentiment_class = "sentiment-positive"
                elif sentiment < -0.2:
                    sentiment_text = "Negative"
                    sentiment_class = "sentiment-negative"
                
                st.markdown(f"""
                <div class="metric-container">
                    <div class="metric-label">Overall Sentiment</div>
                    <div class="metric-value {sentiment_class}">{sentiment_text}</div>
                    <div class="small-text">Based on analysis of recent news articles</div>
                </div>
                """, unsafe_allow_html=True)
            
    # All News tab
        with tabs[2]:
            if not all_articles:
                st.info(f"No news found for {symbol}.")
            else:
                st.write(f"Showing all {len(all_articles)} news items (including general news)")
            
            # Display all news
                for article in all_articles:
                    with st.container():
                        is_quality = article in quality_articles
                        border_color = "#4CAF50" if is_quality else "#9E9E9E"
                    
                    # Get title preview (first 40 characters)
                        title_preview = article['title'][:40] + "..." if len(article['title']) > 40 else article['title']
                    
                        st.markdown(f"""
                        <div class="news-card" style="border-left-color: {border_color}">
                            <h4>{article['title']} {' 🌟' if is_quality else ''}</h4>
                            <p class="source-text">{article['source']} • {self.format_date(article['published_at'])}</p>
                            <p>{article.get('summary', '')[:200]}...</p>
                            <a href="{article['url']}" target="_blank">Read more: {title_preview}</a>
                        </div>
                        """, unsafe_allow_html=True)

    def display_analysis_results(self, symbol: str, company_info: dict, stock_data: dict, quality_articles: list):
        """Display stock analysis results"""
        if not quality_articles:
            st.warning(f"No quality news found for {symbol}. Analysis may be limited.")
        
        # Generate analysis
        with st.spinner("Generating in-depth investment analysis..."):
            analysis = self.generate_investment_analysis(symbol, company_info, stock_data, quality_articles or [])
            
        # Display analysis
        st.markdown(analysis)
        
        # Display summary of key news
        if quality_articles:
            with st.expander("Recent Quality News"):
                for article in quality_articles[:5]:  # Show top 5 articles
                    st.markdown(f"""
                    <div class="news-card" style="border-left-color: #4CAF50">
                        <h4>{article['title']}</h4>
                        <p class="source-text">{article['source']} • {self.format_date(article['published_at'])}</p>
                        <a href="{article['url']}" target="_blank">Read more</a>
                    </div>
                    """, unsafe_allow_html=True)

    def format_date(self, date_str):
        """Format a date string to a readable format"""
        try:
            if isinstance(date_str, int):
                # Unix timestamp
                dt = datetime.fromtimestamp(date_str)
            elif isinstance(date_str, datetime):
                # Already a datetime object
                dt = date_str
            else:
                # ISO format string
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                
            # Convert to local timezone
            local_tz = datetime.now().astimezone().tzinfo
            dt = dt.astimezone(local_tz)
            
            # Format based on how recent it is
            now = datetime.now().astimezone(local_tz)
            diff = now - dt
            
            if diff.days == 0:
                # Today
                hours_ago = diff.seconds // 3600
                if hours_ago == 0:
                    minutes_ago = diff.seconds // 60
                    return f"{minutes_ago} minutes ago"
                return f"{hours_ago} hours ago"
            elif diff.days == 1:
                # Yesterday
                return "Yesterday"
            else:
                # Earlier
                return dt.strftime("%b %d, %Y")
        except:
            # Return as is if parsing fails
            return str(date_str)


def main():
    chatbot = StockNewsChatbot()
    chatbot.run()

if __name__ == "__main__":
    main()