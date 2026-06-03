from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

games = []

class Game(BaseModel):
    name: str
    category: str
    description: str
    image: str

@app.post("/games")
def add_game(game: Game):
    games.append(game.dict())
    return {"success": True}

@app.get("/games")
def get_games():
    return games
