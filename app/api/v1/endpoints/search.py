"""Natural-language search route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_kinoheld_cache,
    get_kinoheld_service,
    get_llm_client,
)
from app.services.cache import KinoheldCache
from app.services.kinoheld import KinoheldService
from app.services.llm_client import LLMClient
from app.services.nl_search import (
    NaturalLanguageQuery,
    NaturalLanguageResult,
    NaturalLanguageSearchService,
)

router = APIRouter(prefix="/search", tags=["search"])

ServiceDep = Annotated[KinoheldService, Depends(get_kinoheld_service)]
CacheDep = Annotated[KinoheldCache, Depends(get_kinoheld_cache)]
LLMDep = Annotated[LLMClient, Depends(get_llm_client)]


@router.post("/natural", response_model=NaturalLanguageResult)
async def natural_language_search(
    request: NaturalLanguageQuery,
    llm_client: LLMDep,
    service: ServiceDep,
    cache: CacheDep,
) -> NaturalLanguageResult:
    """Search cinemas, movies, or shows using a natural-language prompt.

    The prompt is parsed into structured filters (intent, genres, duration,
    year, rating, actors, directors, etc.) by an LLM, then executed against
    Kinoheld with deterministic post-filtering. Set `useCache: true` to query
    the local Kinoheld cache instead of the live API.
    """
    search_service = NaturalLanguageSearchService(llm_client)
    return await search_service.search(request, service, cache)
