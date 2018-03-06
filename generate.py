import requests
import markdown
import hashlib
import json
import os
from datetime import datetime

from jinja2 import Environment, FileSystemLoader


def parse_date(date):
    return datetime.strptime(date[:-1], '%Y-%m-%dT%H:%M:%S') #2018-02-09T18:28:39Z')

def set_cache(url, result):
    filename = os.path.join('cache', url_hash(url) + '.json')
    json.dump(result, open(filename, 'w'))


def get_cache(url):
    filename = os.path.join('cache', url_hash(url) + '.json')
    if os.path.exists(filename):
        print 'Using cache: {}'.format(filename)
        return json.load(open(filename, 'r'))

def url_hash(url):
    hsh = hashlib.md5()
    hsh.update(url)
    return hsh.hexdigest()

def get(url):
    root = 'https://api.github.com'
    if (not url.startswith(root)):
        url = root + url
    
    cached = get_cache(url)
    if cached:
        return cached

    token = os.getenv("GITHUB_TOKEN", 'e1f89827a30093f3ba507a199c4c989730ca680b')
    accept = 'application/vnd.github.inertia-preview+json'
    if 'timeline' in url:
        accept = 'application/vnd.github.mockingbird-preview'
    headers = {'Accept': accept, 'Authorization': 'token {}'.format(token)}
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    res_json = res.json()
    set_cache(url, res_json)
    return res_json

projects_data = {}

def base_url(owner, repo):
    return '/repos/{}/{}'.format(owner, repo)

def get_data(owner, repo):
    projects = get(base_url(owner, repo) + '/projects')
    for project in projects:
   
        this_project = {
            'project': project,
            'columns': {},
            'cards': {},
            'contents_order': [],
            'contents': {},
            'timeline_changes': {}
        }
        columns = get(project['columns_url'])
        for column in columns:
            this_project['columns'][column['id']] = column

            cards = get(column['cards_url'])
            for card in cards:
                # We only want issues and they have a content URL on them.
                if 'content_url' in card:
                    this_project['cards'][card['url']] = card
                    contents = get(card['content_url'])
                    this_project['contents_order'].append([contents['title'], contents['url']])
                    
                    timeline_url = base_url(owner, repo) + '/issues/{}/timeline'.format(contents['number'])
                    contents['timeline_url'] = timeline_url
                    contents['body'] = contents['body'][:40] + '...' 

                    this_project['contents'][contents['url']] = contents
                    
                    timeline = get(timeline_url)
                    timeline_changes = []
                    for line in timeline:
                        if line['event'] in ('labeled', 'commented'):
                            line['created_at'] = parse_date(line['created_at'])
                            if 'body' in line:
                                line['body'] = line['body'][:80] + '...' 
                            timeline_changes.append(line)

                    this_project['timeline_changes'][timeline_url] = reversed(timeline_changes[:-1])

            this_project['contents_order'] = sorted(this_project['contents_order'])

        projects_data[project['id']] =  this_project


get_data('mozilla', 'activity-stream-okrs')

env = Environment(loader=FileSystemLoader('.'))
template = env.get_template('template.html')

context = {"projects_data": projects_data}
html = template.render(context)
open('docs/index.html', 'w').write(html.encode('utf-8'))
