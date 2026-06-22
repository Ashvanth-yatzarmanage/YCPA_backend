import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client():

    from ycpa.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c



class TestHealthEndpoint:

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_correct_shape(self, client):
        response = await client.get("/health")
        data     = response.json()

        assert "status" in data
        assert "app"    in data
        assert "env"    in data

    @pytest.mark.asyncio
    async def test_health_status_is_ok(self, client):
        response = await client.get("/health")
        assert response.json()["status"] == "ok"



class TestNotFound:

    @pytest.mark.asyncio
    async def test_unknown_route_returns_404(self, client):
        response = await client.get("/this-does-not-exist")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_404_follows_problem_detail_shape(self, client):
        response = await client.get("/this-does-not-exist")
        data     = response.json()

        assert "status"     in data
        assert "code"       in data
        assert "detail"     in data
        assert "request_id" in data
        assert "timestamp"  in data



class TestProtectedWithoutAuth:

    @pytest.mark.asyncio
    async def test_me_without_token_returns_401(self, client):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_401_follows_problem_detail_shape(self, client):
        response = await client.get("/api/v1/auth/me")
        data     = response.json()

        assert data["status"] == 401
        assert data["code"]   == "UNAUTHORIZED"
        assert "request_id"   in data
