#First time deployment:
docker build -t jbrowse .

#Serve JBrowse everytime
docker run -v ${JBROWSE_DATA_DIR}:/jbrowse2/data --rm -u $(id -u ${USER}):$(id -g ${USER}) -v $PWD:$PWD \
    --name jbrowse -p 3000:3000 -it jbrowse npx serve .

#RUN ./carga_jb.py (targetpathogenweb folder)
