import requests
import pprint
import pandas as pd

# function to read API key from text file
def get_api_key(filepath):
    with open(filepath, 'r') as file:
        return file.read().strip()

# function to get data from API
def get_ball_data(endpoint, api_key, params=None):
    base_url = f"https://api.balldontlie.io/v1/{endpoint}"
    headers = {
        "Authorization": f"{api_key}"
    }

    if params is None:
        params = {}

    all_data = []

    while True:
        response = requests.get(base_url, headers=headers, params=params)
        response.raise_for_status() # raise exception for HTTP errors

        # convert response to json, then add to previous responses (if exists)
        data = response.json()
        all_data.extend(data['data'])
    
        # check if there is a next page, if not break loop
        if 'next_cursor' in data['meta']:
            next_cursor = data['meta']['next_cursor']
            if next_cursor >= 3000: # stop going to next page after 3000
                break
            params['cursor'] = next_cursor
        else:
            break

    return pd.DataFrame(all_data)

api_key = get_api_key('secrets/api_key.txt')

# players data
players = get_ball_data("players", api_key, {"per_page": 100})

# Print the results to verify
pprint.pprint(players)

