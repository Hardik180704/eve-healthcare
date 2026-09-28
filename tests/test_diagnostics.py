from tests.conftest import auth_headers, login, register, seed_centre_and_test


class TestCentres:
    def test_create_centre_requires_auth(self, client):
        response = client.post(
            "/diagnostics/centres",
            json={"name": "C", "address": "A", "city": "X"},
        )
        assert response.status_code == 401

    def test_create_and_get_centre(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])

        created = client.post(
            "/diagnostics/centres",
            json={"name": "HealthLab", "address": "2 Park Lane", "city": "Delhi"},
            headers=headers,
        )
        assert created.status_code == 201
        centre_id = created.json()["id"]

        fetched = client.get(f"/diagnostics/centres/{centre_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "HealthLab"
        assert fetched.json()["tests"] == []

    def test_list_centres(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])
        for city in ("Delhi", "Mumbai"):
            client.post(
                "/diagnostics/centres",
                json={"name": f"Centre {city}", "address": "A", "city": city},
                headers=headers,
            )
        response = client.get("/diagnostics/centres", headers=headers)
        assert response.status_code == 200
        assert {c["city"] for c in response.json()} == {"Delhi", "Mumbai"}

    def test_get_nonexistent_centre(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])
        assert client.get("/diagnostics/centres/9999", headers=headers).status_code == 404


class TestTests:
    def test_create_test_and_duplicate_code(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])

        first = client.post(
            "/diagnostics/tests",
            json={"code": "cbc", "name": "Complete Blood Count"},
            headers=headers,
        )
        assert first.status_code == 201
        assert first.json()["code"] == "CBC"  # codes are normalized to upper case

        duplicate = client.post(
            "/diagnostics/tests",
            json={"code": "CBC", "name": "Another name"},
            headers=headers,
        )
        assert duplicate.status_code == 409

    def test_list_tests(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])
        client.post(
            "/diagnostics/tests",
            json={"code": "LFT", "name": "Liver Function Test"},
            headers=headers,
        )
        response = client.get("/diagnostics/tests", headers=headers)
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestCentreTests:
    def test_associate_test_with_price(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])
        centre_id, test_id = seed_centre_and_test(client, headers, price="499.99")

        detail = client.get(f"/diagnostics/centres/{centre_id}", headers=headers)
        tests = detail.json()["tests"]
        assert len(tests) == 1
        assert tests[0]["id"] == test_id
        assert str(tests[0]["price"]) in ("499.00", "499.99", "499.0", "499")

    def test_associate_duplicate_rejected(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])
        centre_id, test_id = seed_centre_and_test(client, headers)
        response = client.post(
            f"/diagnostics/centres/{centre_id}/tests",
            json={"test_id": test_id, "price": "100.00"},
            headers=headers,
        )
        assert response.status_code == 409

    def test_associate_nonexistent_test(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])
        centre = client.post(
            "/diagnostics/centres",
            json={"name": "C", "address": "A", "city": "X"},
            headers=headers,
        )
        response = client.post(
            f"/diagnostics/centres/{centre.json()['id']}/tests",
            json={"test_id": 9999, "price": "100.00"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_associate_invalid_price_rejected(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])
        centre_id, test_id = seed_centre_and_test(client, headers)
        response = client.post(
            f"/diagnostics/centres/{centre_id}/tests",
            json={"test_id": test_id, "price": "0"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_list_centre_tests(self, client):
        register(client)
        headers = auth_headers(login(client).json()["access_token"])
        centre_id, _ = seed_centre_and_test(client, headers)
        response = client.get(f"/diagnostics/centres/{centre_id}/tests", headers=headers)
        assert response.status_code == 200
        assert len(response.json()) == 1
