"""High-level service for the Kinoheld GraphQL API."""

from typing import Any

from app.schemas.cinema import Cinema, CinemaSearchParams
from app.schemas.city import City, CitySearchParams
from app.schemas.movie import Genre, Movie, MovieSearchParams
from app.schemas.show import Show, ShowSearchParams
from app.services.graphql_client import GraphQLClient


class KinoheldService:
    """Business logic layer translating REST params to GraphQL queries."""

    def __init__(self, client: GraphQLClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    # Cinemas
    # ------------------------------------------------------------------
    async def search_cinemas(self, params: CinemaSearchParams) -> list[Cinema]:
        query = """
        query SearchCinemas(
          $search: String,
          $location: String,
          $distance: Int,
          $limit: Int,
          $onlyBookable: Boolean,
          $isOpenAir: Boolean,
          $isDriveIn: Boolean
        ) {
          cinemas(
            search: $search,
            location: $location,
            distance: $distance,
            limit: $limit,
            onlyBookable: $onlyBookable,
            isOpenAir: $isOpenAir,
            isDriveIn: $isDriveIn
          ) {
            id
            name
            street
            city { id name urlSlug }
            distance
            coordinates { latitude longitude }
            postcode { id postcode }
            phonenumber
            detailUrl { url }
            thumbnail { url }
            heroImage { url }
            urlSlug
            isDriveInCinema
            isOpenAirCinema
            isStationaryCinema
          }
        }
        """
        variables = self._drop_nones(params.model_dump(mode="json", by_alias=True))
        data = await self.client.execute(query, variables=variables)
        return [Cinema.model_validate(item) for item in data.get("cinemas", [])]

    async def get_cinema(self, cinema_id: str) -> Cinema:
        query = """
        query GetCinema($id: ID!) {
          cinema(id: $id) {
            id
            name
            street
            city { id name urlSlug }
            distance
            coordinates { latitude longitude }
            postcode { id postcode }
            phonenumber
            detailUrl { url }
            thumbnail { url }
            heroImage { url }
            urlSlug
            isDriveInCinema
            isOpenAirCinema
            isStationaryCinema
          }
        }
        """
        data = await self.client.execute(query, variables={"id": cinema_id})
        cinema = data.get("cinema")
        if not cinema:
            from app.core.exceptions import KinoheldNotFoundError

            raise KinoheldNotFoundError(f"Cinema {cinema_id} not found")
        return Cinema.model_validate(cinema)

    # ------------------------------------------------------------------
    # Movies
    # ------------------------------------------------------------------
    async def search_movies(self, params: MovieSearchParams) -> list[Movie]:
        query = """
        query SearchMovies(
          $search: String,
          $location: String,
          $distance: Int,
          $limit: Int,
          $playing: ShowsPlayingFilterEnum
        ) {
          movies(
            search: $search,
            location: $location,
            distance: $distance,
            limit: $limit,
            playing: $playing
          ) {
            id
            title
            description
            additionalDescription
            duration
            genres { id name urlSlug }
            directors { id name }
            actors { id name }
            productionYear
            thumb { url }
            heroImage { url }
            detailUrl { url }
            urlSlug
            imdbRating
            imdbVotes
          }
        }
        """
        variables = self._drop_nones(params.model_dump(mode="json", by_alias=True))
        data = await self.client.execute(query, variables=variables)
        return [Movie.model_validate(item) for item in data.get("movies", [])]

    async def get_movie(self, movie_id: str) -> Movie:
        query = """
        query GetMovie($id: ID!) {
          movie(id: $id) {
            id
            title
            description
            additionalDescription
            duration
            genres { id name urlSlug }
            directors { id name }
            actors { id name }
            productionYear
            thumb { url }
            heroImage { url }
            detailUrl { url }
            urlSlug
            imdbRating
            imdbVotes
          }
        }
        """
        data = await self.client.execute(query, variables={"id": movie_id})
        movie = data.get("movie")
        if not movie:
            from app.core.exceptions import KinoheldNotFoundError

            raise KinoheldNotFoundError(f"Movie {movie_id} not found")
        return Movie.model_validate(movie)

    # ------------------------------------------------------------------
    # Shows
    # ------------------------------------------------------------------
    async def search_shows(self, params: ShowSearchParams) -> list[Show]:
        # Only include the movie filter in the query when a movieId is supplied.
        # Sending movie: {id: null} to Kinoheld returns an empty result set.
        movie_arg = "movie: {id: $movieId}" if params.movie_id else ""
        movie_var = "$movieId: ID" if params.movie_id else ""
        query = f"""
        query SearchShows($cinemaId: ID!, $date: String, $days: Int, {movie_var}) {{
          shows(cinemaId: $cinemaId, date: $date, days: $days, {movie_arg}) {{
            id
            name
            beginning {{ formatted timestamp }}
            admission {{ formatted timestamp }}
            duration
            flags {{ name code category }}
            detailUrl {{ url }}
            isSoldOut
            movie {{
              id
              title
              description
              additionalDescription
              duration
              genres {{ id name }}
              thumb {{ url }}
              detailUrl {{ url }}
              urlSlug
            }}
            auditorium {{ id name seatCount }}
          }}
        }}
        """
        variables = self._drop_nones(params.model_dump(mode="json", by_alias=True))
        data = await self.client.execute(query, variables=variables)
        return [Show.model_validate(item) for item in data.get("shows", [])]

    async def get_show(self, show_id: str) -> Show:
        query = """
        query GetShow($id: ID!) {
          show(id: $id) {
            id
            name
            beginning { formatted timestamp }
            admission { formatted timestamp }
            duration
            flags { name code category }
            detailUrl { url }
            isSoldOut
            movie {
              id
              title
              description
              additionalDescription
              duration
              genres { id name }
              thumb { url }
              detailUrl { url }
              urlSlug
            }
            auditorium { id name seatCount }
          }
        }
        """
        data = await self.client.execute(query, variables={"id": show_id})
        show = data.get("show")
        if not show:
            from app.core.exceptions import KinoheldNotFoundError

            raise KinoheldNotFoundError(f"Show {show_id} not found")
        return Show.model_validate(show)

    # ------------------------------------------------------------------
    # Cities
    # ------------------------------------------------------------------
    async def search_cities(self, params: CitySearchParams) -> list[City]:
        query = """
        query SearchCities($search: String, $location: String, $distance: Int, $limit: Int) {
          cities(search: $search, location: $location, distance: $distance, limit: $limit) {
            id
            name
            urlSlug
            coordinates { latitude longitude }
            detailUrl { url }
          }
        }
        """
        variables = self._drop_nones(params.model_dump(mode="json", by_alias=True))
        data = await self.client.execute(query, variables=variables)
        return [City.model_validate(item) for item in data.get("cities", [])]

    async def get_city(self, city_id: str) -> City:
        query = """
        query GetCity($name: String) {
          city(name: $name) {
            id
            name
            urlSlug
            coordinates { latitude longitude }
            detailUrl { url }
          }
        }
        """
        data = await self.client.execute(query, variables={"name": city_id})
        city = data.get("city")
        if not city:
            from app.core.exceptions import KinoheldNotFoundError

            raise KinoheldNotFoundError(f"City {city_id} not found")
        return City.model_validate(city)

    async def city_by_ip(self) -> City:
        query = """
        query CityByIp {
          cityByIp {
            id
            name
            urlSlug
            coordinates { latitude longitude }
            detailUrl { url }
          }
        }
        """
        data = await self.client.execute(query)
        city = data.get("cityByIp")
        if not city:
            from app.core.exceptions import KinoheldNotFoundError

            raise KinoheldNotFoundError("Could not determine city by IP")
        return City.model_validate(city)

    # ------------------------------------------------------------------
    # Genres
    # ------------------------------------------------------------------
    async def list_genres(self) -> list[Genre]:
        query = """
        query ListGenres {
          genres {
            id
            name
            urlSlug
          }
        }
        """
        data = await self.client.execute(query)
        return [Genre.model_validate(item) for item in data.get("genres", [])]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _drop_nones(mapping: dict[str, Any]) -> dict[str, Any]:
        """Remove None values before sending to GraphQL to rely on server defaults."""
        return {k: v for k, v in mapping.items() if v is not None}
