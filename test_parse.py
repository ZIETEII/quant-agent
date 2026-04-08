from bs4 import BeautifulSoup
with open('templates/index.html') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')
for tab_id in ['tab-portfolio', 'tab-config', 'tab-clones', 'tab-brain', 'tab-graficas']:
    el = soup.find(id=tab_id)
    if el:
        parents = [p.get('id') for p in el.parents if p.get('id')]
        print(f"{tab_id} is inside: {parents}")
