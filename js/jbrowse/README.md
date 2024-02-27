#First time deployment:
docker build -t jbrowse .


#First set the enviroment variables (/targetpathogenweb/exports.sh)
source exports.sh

#Serve JBrowse everytime
docker run -v ${JBROWSE_DATA_DIR}:/jbrowse2/data --rm -u $(id -u ${USER}):$(id -g ${USER}) -v $PWD:$PWD \
    --name jbrowse -p 3000:3000 -it jbrowse npx serve .

#RUN (located on /targetpathogenweb)
./carga_jb.py  

