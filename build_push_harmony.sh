# docker login -u harmonydata
# cd harmony; git pull; cd ..; git add harmony; git commit -m "update submodule"; git push
export COMMIT_ID=`git show -s --format=%ci_%h | sed s/[^_a-z0-9]//g | sed s/0[012]00_/_/g` && docker build -t harmonyapi -t harmonyapi:$COMMIT_ID -t harmonydata/harmonyapi -t harmonydata/harmonyapi:$COMMIT_ID -t harmonydata/harmonyapi:latest --build-arg COMMIT_ID=$COMMIT_ID . && docker push harmonydata/harmonyapi:$COMMIT_ID && docker push harmonydata/harmonyapi:latest && echo "The container version is $COMMIT_ID"
# docker run -p 8000:80 harmonydata/harmonyapi:$COMMIT_ID
