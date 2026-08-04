"""Search routes: natural language and structured/filter panel."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_cinetixx_cache,
    get_kinoheld_cache,
    get_kinoheld_service,
    get_llm_client,
    get_yorck_cache,
)
from app.services.cache import KinoheldCache
from app.services.cinetixx_cache import CinetixxCache
from app.services.kinoheld import KinoheldService
from app.services.llm_client import LLMClient
from app.services.nl_search import (
    NaturalLanguageQuery,
    NaturalLanguageResult,
    NaturalLanguageSearchService,
    SearchResult,
    SourceCaches,
    StructuredSearchQuery,
)
from app.services.yorck_cache import YorckCache

router = APIRouter(prefix="/search", tags=["search"])

ServiceDep = Annotated[KinoheldService, Depends(get_kinoheld_service)]
CacheDep = Annotated[KinoheldCache, Depends(get_kinoheld_cache)]
LLMDep = Annotated[LLMClient, Depends(get_llm_client)]
CinetixxCacheDep = Annotated[CinetixxCache, Depends(get_cinetixx_cache)]
YorckCacheDep = Annotated[YorckCache, Depends(get_yorck_cache)]


@router.post("/natural", response_model=NaturalLanguageResult)
async def natural_language_search(
    request: NaturalLanguageQuery,
    llm_client: LLMDep,
    service: ServiceDep,
    cache: CacheDep,
    cinetixx_cache: CinetixxCacheDep,
    yorck_cache: YorckCacheDep,
) -> NaturalLanguageResult:
    """Search cinemas, movies, or shows using a natural-language prompt.

    The prompt is parsed into structured filters (intent, genres, duration,
    year, rating, actors, directors, etc.) by an LLM, then executed across every
    source with deterministic post-filtering. Results carry `source` and
    `sourceId` tags.

    `useCache` governs the Kinoheld path only. Cinetixx and Yorck are always read
    from their periodic caches, because a live read of either means pulling a
    whole provider programme.
    """
    search_service = NaturalLanguageSearchService(llm_client)
    return await search_service.search(
        request,
        service,
        cache,
        SourceCaches(cinetixx=cinetixx_cache, yorck=yorck_cache),
    )


@router.post("/structured", response_model=SearchResult)
async def structured_search(
    request: StructuredSearchQuery,
    llm_client: LLMDep,
    service: ServiceDep,
    cache: CacheDep,
    cinetixx_cache: CinetixxCacheDep,
    yorck_cache: YorckCacheDep,
) -> SearchResult:
    """Search cinemas, movies, or shows using explicit UI filters.

    This endpoint skips LLM parsing and applies the provided filters
    deterministically across every source. Ideal for filter panels, sliders, and
    toggles. `useCache` governs the Kinoheld path only; Cinetixx and Yorck are
    always read from their periodic caches.
    """
    search_service = NaturalLanguageSearchService(llm_client)
    return await search_service.structured_search(
        request,
        service,
        cache,
        SourceCaches(cinetixx=cinetixx_cache, yorck=yorck_cache),
    )
