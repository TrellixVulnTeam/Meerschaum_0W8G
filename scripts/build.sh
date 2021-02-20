#! /bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
. "$DIR"/config.sh
cd "$PARENT"

### Delete leftover files before building.
./scripts/clean.sh

### Build documentation.
./scripts/docs.sh

### Experimental features must be enabled and docker buildx must be installed.
### Run setup.sh to ensure everything is set up.

[ ! -d requirements ] && mkdir -p requirements
for t in "${tags[@]}"; do
  new_reqs=$(python -m meerschaum show packages "$t" --nopretty)
  old_reqs=$(cat requirements/"$t".txt 2>/dev/null)
  [ -z "$old_reqs" ] || [ "$new_reqs" != "$old_reqs" ] && echo "$new_reqs" > requirements/"$t".txt
done

docker pull "$python_image"
for t in "${tags[@]}"; do
  docker buildx build --push --build-arg dep_group="$t" --platform "$platforms" -t "$image:$t" . || exit 1
done
docker tag "$image:api" "$image:latest"
# docker build --squash -t "$image" . || exit 1

### Build the pip package for uploading to PyPI.
python setup.py sdist

