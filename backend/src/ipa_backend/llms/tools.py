import wikipedia
from pydantic_ai import ModelRetry
from loguru import logger

wikipedia.set_user_agent("ipa_search/0.1 (https://scads.ai/research/applied-ai-and-big-data/life-science-and-medicine/projects/intelligent-patient-record-ipa/)")


def search_wikipedia(query: str) -> tuple[str]:
    """Search for articles in German Wikipedia.

    Args:
        query: search query in German
    """

    wikipedia.set_lang("de")

    return wikipedia.search(query)

def get_wikipedia_article(article_name: str) -> str | None:
    """Retrieve a single German Wikipedia article.

    Args:
        article name: name of German Wikipedia article as retrieved from search_wikipedia tool
    """

    wikipedia.set_lang("de")

    try:
        page = wikipedia.page(title=article_name, auto_suggest=False)
        return page.content

    except Exception as e:
        logger.error(str(e))
        raise ModelRetry(f'{article_name} is ambiguous. It might refer to one of the following articles: {str(e)}')
