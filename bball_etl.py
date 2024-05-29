import requests
import pprint

def get_ball_data(endpoint, api_key, params=None):
    url = f"https://api.balldontlie.io/v1/{endpoint}"
    headers = {
        "Authorization": f"{api_key}"
    }
    response = requests.get(url, headers=headers, params=params)
    return response.json()

api_key = "535c20e5-0e08-453c-9a3d-8779198f763a"

# players data
players = get_ball_data("players?cursor=2", api_key, {"per_page": 100})

# games data

# Print the results to verify
pprint.pprint(players)
