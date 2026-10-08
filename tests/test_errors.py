async def test_unknown_url_returns_json_404(async_client):
    response = await async_client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not found"}}
