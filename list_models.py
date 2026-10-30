"""List the Nemotron models your Nebius key can access. Never prints the key."""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.environ["NEBIUS_API_KEY"], base_url=os.environ["NEBIUS_BASE_URL"])

ids = sorted(m.id for m in client.models.list())
nemotron = [i for i in ids if "nemotron" in i.lower()]

print(f"{len(ids)} models available, {len(nemotron)} Nemotron:")
for i in nemotron:
    print("  ", i)
