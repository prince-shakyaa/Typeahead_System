import random
import os

# Base vocabularies
TECH_TERMS = ["python", "java", "docker", "kubernetes", "aws", "react", "node", "linux", "golang", "redis", "nginx", "mysql", "mongodb", "fastapi", "django", "spring", "flask", "ruby", "rust", "c++", "ubuntu", "git", "bash", "vim", "vscode", "apple", "app", "application", "api", "banana", "band", "bandwidth"]
MODIFIERS = ["tutorial", "download", "documentation", "examples", "interview questions", "course", "certification", "for beginners", "best practices", "architecture", "deployment", "vs", "setup", "install", "cheat sheet", "error", "fix", "logs", "performance", "scaling"]
VERSIONS = ["latest", "2024", "v2", "v3", "1.0", "mac", "windows", "linux"]

def generate_dataset(filename="dataset.txt", target_count=100000):
    queries = set()
    print(f"Generating {target_count} unique queries...")
    
    # Generate unique queries
    while len(queries) < target_count:
        term = random.choice(TECH_TERMS)
        mod = random.choice(MODIFIERS)
        version = random.choice(VERSIONS)
        
        r = random.random()
        if r < 0.4:
            q = term
        elif r < 0.7:
            q = f"{term} {mod}"
        elif r < 0.9:
            q = f"{term} {version}"
        else:
            q = f"{term} {mod} {version}"
            
        queries.add(q)
        
        # Also add some random letter combinations to fill out the 100K quickly
        if len(queries) > 5000:
            import string
            rand_str = ''.join(random.choices(string.ascii_lowercase, k=random.randint(4, 10)))
            queries.add(rand_str)

    # Convert to list and sort for stable output
    queries_list = sorted(list(queries))
    
    # Generate Zipfian-like distribution for counts (popular items get exponentially more counts)
    print("Writing to file...")
    with open(filename, "w", encoding="utf-8") as f:
        for i, q in enumerate(queries_list):
            # i determines rank, lower i means less popular (because sorted alphabetically, it's just random rank)
            # We want a few massive hits and a long tail of 1s and 2s.
            rank = random.randint(1, len(queries_list))
            count = max(1, int(1000000 / (rank ** 1.2))) 
            f.write(f"{q}\t{count}\n")
            
    print(f"Done! Dataset saved to {filename}")

if __name__ == "__main__":
    generate_dataset()
