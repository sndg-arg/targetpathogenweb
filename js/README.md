docker build -t webpack .

# -u $(id -u ${USER}):$(id -g ${USER})
docker run --rm  -w $PWD -v $PWD:$PWD webpack bash -c 'npm install'
sudo chown -R ${USER}:$(id -g ${USER}) .npm node_modules


# las lineas de a continuacion arreglan el codigo de bootstrap y msa que por algun motivo no funcionan cuando se descargan desde npm
sed -i 's|require("bootstrap/js/tooltip.js")|require("bootstrap/js/dist/tooltip.js")|' ./node_modules/feature-viewer/lib/index.js
sed -i 's|require("bootstrap/js/popover.js")|require("bootstrap/js/dist/popover.js")|' ./node_modules/feature-viewer/lib/index.js
sed -i 's|// FIX scrollbars on Mac||' ./node_modules/msa/css/msa.css

docker run --rm -w $PWD -v $PWD:$PWD webpack npm run build
sudo chown -R ${USER}:$(id -g ${USER}) bundle.js
mkdir  ../static/
cp bundle.js ../static/

