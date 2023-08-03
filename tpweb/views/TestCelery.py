from django.http import HttpResponse

#from sndgapp.tasks.testtask import get_users_count
#from sndgwebapp.tasks.testtask import get_users_count
from sndgjobs.models.SNDGJob import SNDGJob
from sndgjobs.tasks.submit_job_task import submit_job_task

def test_celery(request):

    from django.db import transaction
    with transaction.atomic():
        job = SNDGJob()
        job.cmd = "ssh slurmqb sbatch --export=db=/grupos/public/databases/uniprot/uniprot_sprot.fasta,query=run/pepe.fasta,out=run/pepe.tbl ./scripts/blast.slurm"
        job.save()

    job = submit_job_task.delay(job.id)
    #import json
    #ret = get_users_count.delay()
    return HttpResponse(str(job.id))