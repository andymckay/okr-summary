import requests
import gfm
import hashlib
import json
import os
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

all_repos = []
all_projects = {}
# Since milestones can cross projects, let's seperate them out.
all_milestones = {}

if os.getenv('OKR_READ_CACHE'):
    # This is much faster and helpful for development.
    print 'Note: using the built-in cached queries because OKR_READ_CACHE is set.'
else:
    print 'Note: NOT using cached queries.'


def parse_date(date):
    return datetime.strptime(date[:-1], '%Y-%m-%dT%H:%M:%S') #2018-02-09T18:28:39Z')


def contrast(color):
    r, g, b = color[:2], color[2:4], color[4:]
    total = (int(r, 16) * 255 + int(g, 16) * 587 + int(b, 16) * 114) / 1000
    if total > 123:
        return 'black'
    else:
        return 'white'


def summarize(milestone):
    issues = {'open': 0, 'closed': 0, 'total': 0, 'percent': 0}
    for issue in milestone['items']:
        issues['total'] += 1
        if issue['state'] == 'open':
            issues['open'] += 1
        elif issue['state'] == 'closed':
            issues['closed'] += 1

    if issues['total']:
        issues['percent'] = int(issues['closed']/float(issues['total'])*100)
    return issues 

def set_cache(url, result):
    filename = os.path.join('cache', url_hash(url) + '.json')
    json.dump(result, open(filename, 'w'))


def get_cache(url):
    filename = os.path.join('cache', url_hash(url) + '.json')
    if os.getenv('OKR_READ_CACHE') and os.path.exists(filename):
        return json.load(open(filename, 'r'))


def url_hash(url):
    hsh = hashlib.md5()
    hsh.update(url)
    return hsh.hexdigest()


def get(url):
    root = 'https://api.github.com/'
    if (not url.startswith(root)):
        url = root + url
    
    cached = get_cache(url)
    if cached:
        return cached

    token = os.getenv("GITHUB_OKR_TOKEN", None)
    assert token, "Specify a token in the GITHUB_OKR_TOKEN environment variable."
    accept = 'application/vnd.github.inertia-preview+json'
    if 'timeline' in url:
        accept = 'application/vnd.github.mockingbird-preview'
    headers = {'Accept': accept, 'Authorization': 'token {}'.format(token)}
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    res_json = res.json()
    set_cache(url, res_json)
    return res_json


def join(*args):
    return '/'.join(args)


def get_repo(owner, repo):
    return get(join('repos', owner, repo))


def get_data(owner, repo):
    projects_data = {}
    url = join(owner, repo)
    projects = get(join('repos', url, 'projects'))
    for project in projects:
        if project['state'] == 'closed':
            continue

        all_projects.setdefault(url, [])
        all_projects[url].append(project)

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
                    
                    timeline_url = join('repos', owner, repo, 'issues', str(contents['number']), 'timeline')
                    contents['timeline_url'] = timeline_url
                    contents['body'] = gfm.markdown(contents['body'])

                    this_project['contents'][contents['url']] = contents
                    
                    timeline = get(timeline_url)
                    timeline_changes = []
                    for line in timeline:
                        if line['event'] in ('labeled', 'commented'):
                            line['created_at'] = parse_date(line['created_at'])
                            if 'body' in line:
                                line['body'] = gfm.markdown(line['body'])

                            timeline_changes.append(line)

                    this_project['timeline_changes'][timeline_url] = timeline_changes[:-1]
                    
                    if contents['milestone'] and contents['milestone']['id'] not in all_milestones:
                        milestone_url = join('search', 'issues') + '?q=milestone:"{}"'.format(contents['milestone']['title'])
                        milestone = get(milestone_url)
                        milestone['issue_summary'] = summarize(milestone)
                        all_milestones[contents['milestone']['id']] = milestone

            this_project['contents_order'] = sorted(this_project['contents_order'])

        projects_data[project['id']] = this_project

    all_projects[url] = reversed(all_projects[url])
    return projects_data


data = json.load(open('config.json', 'r'))
for repo in data['repos']:
    org, name = repo.split('/')
    projects_data = get_data(org, name)
    all_repos.append(get_repo(org, name))

    env = Environment(loader=FileSystemLoader('.'))
    env.filters['contrast'] = contrast
    template = env.get_template('project-template.html')

    context = {"projects_data": projects_data, "milestones_data": all_milestones}
    html = template.render(context)
    open('docs/{}.html'.format(name), 'w').write(html.encode('utf-8'))


# Write out an index.html.
env = Environment(loader=FileSystemLoader('.'))
env.filters['contrast'] = contrast
template = env.get_template('index-template.html')
html = template.render({"repos": all_repos, "projects": all_projects})
open('docs/index.html', 'w').write(html.encode('utf-8'))
