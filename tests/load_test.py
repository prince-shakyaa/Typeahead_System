from locust import HttpUser, task, between
import random

class TypeaheadUser(HttpUser):
    # Wait between 0.1 to 1 second between tasks
    wait_time = between(0.1, 1)
    
    # Common prefixes to test
    prefixes = [
        "a", "app", "b", "ba", "c", "ca", 
        "d", "do", "p", "py", "s", "so", 
        "t", "ty", "r", "re"
    ]
    
    # Common full words to log search
    search_queries = [
        "apple", "application", "banana", "cat", 
        "docker", "python", "software", "typeahead",
        "react", "redis"
    ]

    @task(3)
    def suggest_api(self):
        """Simulate users typing and getting suggestions (higher frequency)"""
        prefix = random.choice(self.prefixes)
        self.client.get(f"/suggest?q={prefix}", name="/suggest")

    @task(1)
    def search_api(self):
        """Simulate users selecting a search result (lower frequency)"""
        query = random.choice(self.search_queries)
        self.client.post("/search", json={"query": query}, name="/search")
