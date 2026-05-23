# Tutorial: How to Obtain Data for FastTarget

This tutorial will guide you through the steps to obtain the necessary data for using this pipeline.

## 1. Getting the GenBank (gbk) File

To get the GenBank file (`.gbk`) for your organism, you have a couple of options:

- **NCBI Database**: Download the GenBank file directly from the NCBI website. Visit the [NCBI Genome Database](https://www.ncbi.nlm.nih.gov/genome/) and search for your organism. Once you find the desired genome, you can download the GenBank file from the "Download" section.

- **Annotation Programs**: If you're using an annotation tool like Prokka or PGAP, you can generate the GenBank file as part of the annotation process. Follow the documentation of the respective tool to obtain the GenBank file.

## 2. Obtaining Metabolic Files

To obtain metabolic files, you can use the Pathway Tools program. Here's a brief guide:

1. **Install Pathway Tools**: Download and install Pathway Tools from the official [Pathway Tools website](https://bioinformatics.ai.sri.com/ptools/).

2. **Generate Metabolic Data**: Utilize PathoLogic to create a new Pathway/Genome Database (PGDB) for your organism. This powerful tool predicts metabolic pathways by analyzing a GenBank file with the assistance of the MetaCyc pathway database.

3. **Save and Export**: Once the analysis is complete, export the metabolic files in the required format for use in this pipeline.

     **Export SBML File**:
        - Go to `File > Export > Generate SBML file for > Selected Reactions`.
        - In the `Type` section, select those that are small molecules.

    **Find Chokepoints**:
        - Go to `Tools > Chokepoint Reaction Finder`.
        - Do not select any filters to obtain all possible reactions.
        - You will find the chokepoints file in the `Reports` folder of your PGDB.

    **Create and Export Smartables**:
        - Go to `Smartables > Create New Smartable`, and choose to include `All Genes`.
        - Once the Smartable is created, in `Smartable`, click on `Select Columns to Show` and make sure to select the `Reactions` column.
        - Then go to `Smartable > Export Smarttable > Tab-Delimited File`, and ensure that `Identifiers` are selected to include the IDs.

## 3. Obtaining the Taxonomy ID

To find the taxonomy ID for your species:

1. **Visit NCBI**: Go to the [NCBI Taxonomy Database](https://www.ncbi.nlm.nih.gov/taxonomy).

2. **Search for Your Species**: Enter the name of your species or strain in the search bar.

3. **Find the Tax ID**: Locate the taxonomy ID associated with your species and the ID of your strain.
