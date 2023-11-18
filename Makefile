CHIRPY_DIR := chirpy
GH_PAGES_DIR := gh-pages
DEPLOY_DATE := $(shell date +'%Y-%m-%d %H:%M:%S')

build: chirpy gh-pages
	@cd ./$(CHIRPY_DIR) && bundle exec jekyll build

chirpy: 
	@if [ ! -d "$(CHIRPY_DIR)" ]; then \
		git worktree add --guess-remote $(CHIRPY_DIR); \
	fi

gh-pages:
	@if [ ! -d "$(GH_PAGES_DIR)" ]; then \
		git worktree add --guess-remote $(GH_PAGES_DIR); \
	fi

deploy: build
	@rm -rf $(GH_PAGES_DIR)/*
	@cp -r ./$(CHIRPY_DIR)/_site/* $(GH_PAGES_DIR)/
	@cd $(GH_PAGES_DIR) && git add --all
	@cd $(GH_PAGES_DIR) && git commit -m "Deployed on $(DEPLOY_DATE)"
	@cd $(GH_PAGES_DIR) && git push
