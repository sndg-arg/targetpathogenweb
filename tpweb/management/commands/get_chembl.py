
import requests


def get_chembl_target_id(uniprot_id):
    """Fetch the ChEMBL target ID corresponding to a UniProt ID."""
    url = f"https://www.ebi.ac.uk/chembl/api/data/target?target_components.accession={uniprot_id}"
    response = requests.get(url, headers={"Accept": "application/json"})
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data from ChEMBL API: {response.status_code}")
    data = response.json()
    targets = data.get('targets', [])
    print(targets)
    if not targets:
        raise ValueError(f"No ChEMBL target found for UniProt ID: {uniprot_id}")
    return targets[0]['target_chembl_id']


def get_compounds_for_target(chembl_target_id):
    """Fetch compounds associated with a ChEMBL target ID."""
    url = f"https://www.ebi.ac.uk/chembl/api/data/activity?target_chembl_id={chembl_target_id}"
    response = requests.get(url, headers={"Accept": "application/json"})
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data from ChEMBL API: {response.status_code}")
    data = response.json()
    activities = data.get('activities', [])
    compounds = {activity['molecule_chembl_id'] for activity in activities if 'molecule_chembl_id' in activity}
    return compounds


def main():
    # Example UniProt ID
    uniprot_id = input("Enter UniProt ID: ").strip()

    try:
        print(f"Fetching ChEMBL target for UniProt ID: {uniprot_id}...")
        chembl_target_id = get_chembl_target_id(uniprot_id)
        print(f"ChEMBL Target ID: {chembl_target_id}")
        print(f"Fetching compounds associated with target: {chembl_target_id}...")

        compounds = get_compounds_for_target(chembl_target_id)

        if compounds:
            print(f"Found {len(compounds)} compounds:")
            for compound in compounds:
                print(f"- {compound}")
        else:
            print("No compounds found for this target.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
