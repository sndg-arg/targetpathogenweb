docker build -t jbrowse .
docker run -v $PWD/data:/jbrowse2/data --rm -u $(id -u ${USER}):$(id -g ${USER}) -v $PWD:$PWD \
    --name jbrowse -p 3000:3000 -it jbrowse npx serve .

docker run -v $PWD/data:/jbrowse2/data --rm -u $(id -u ${USER}):$(id -g ${USER}) -v $PWD:$PWD jbrowse jbrowse add-assembly data/NC_003047.genome.fna.bgz --load copy --out data/jbrowse/NC_003047/ --type bgzipFasta


docker run -v $PWD/data:/jbrowse2/data --rm -u $(id -u ${USER}):$(id -g ${USER}) -v $PWD:$PWD jbrowse jbrowse add-track data/NC_003047.gff.bgz --load copy --out data/jbrowse/NC_003047/
