from django.core.management.base import BaseCommand
from django.conf import settings
import mongoengine
from OCRfeature.models import AdminOCRResult, UserOCRResult, OCRResult, UploadedFile
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Clean up orphaned OCR results that reference non-existent uploaded files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed information about each orphaned record',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']
        
        self.stdout.write(self.style.SUCCESS('Starting cleanup of orphaned OCR results...'))
        
        # Get all existing uploaded file IDs
        existing_file_ids = set()
        try:
            for file_doc in UploadedFile.objects.only('id'):
                existing_file_ids.add(str(file_doc.id))
            self.stdout.write(f"Found {len(existing_file_ids)} existing uploaded files")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting uploaded files: {e}"))
            return

        # Clean up each OCR result collection
        collections_to_clean = [
            (AdminOCRResult, 'Admin OCR Results'),
            (UserOCRResult, 'User OCR Results'),
            (OCRResult, 'Legacy OCR Results')
        ]

        total_orphaned = 0
        total_cleaned = 0

        for model_class, collection_name in collections_to_clean:
            self.stdout.write(f"\nChecking {collection_name}...")
            
            orphaned_count = 0
            cleaned_count = 0
            
            try:
                # Get all OCR results for this collection
                all_results = model_class.objects.all()
                total_results = all_results.count()
                self.stdout.write(f"Found {total_results} results in {collection_name}")
                
                orphaned_ids = []
                
                for result in all_results:
                    source_file_id = None
                    try:
                        # Check if result has source_file field (now StringField)
                        if hasattr(result, 'source_file') and result.source_file:
                            source_file_id = result.source_file
                        
                        # Check if the file still exists
                        if source_file_id:
                            if source_file_id not in existing_file_ids:
                                orphaned_ids.append(str(result.id))
                                orphaned_count += 1
                                if verbose:
                                    self.stdout.write(f"  Orphaned: {result.id} -> missing file {source_file_id}")
                        else:
                            # No valid source file reference
                            orphaned_ids.append(str(result.id))
                            orphaned_count += 1
                            if verbose:
                                self.stdout.write(f"  Orphaned: {result.id} -> no valid source file reference")
                                
                    except Exception as e:
                        # This handles any errors accessing source file
                        orphaned_ids.append(str(result.id))
                        orphaned_count += 1
                        if verbose:
                            self.stdout.write(f"  Orphaned: {result.id} -> error accessing source file: {e}")
                
                if orphaned_ids:
                    if dry_run:
                        self.stdout.write(self.style.WARNING(
                            f"DRY RUN: Would delete {orphaned_count} orphaned records from {collection_name}"
                        ))
                    else:
                        # Delete orphaned records by ID
                        try:
                            from bson import ObjectId
                            object_ids = [ObjectId(oid) for oid in orphaned_ids]
                            result = model_class.objects(id__in=object_ids).delete()
                            cleaned_count = len(orphaned_ids)
                            self.stdout.write(self.style.SUCCESS(
                                f"Deleted {cleaned_count} orphaned records from {collection_name}"
                            ))
                        except Exception as delete_error:
                            self.stdout.write(self.style.ERROR(
                                f"Error deleting orphaned records from {collection_name}: {delete_error}"
                            ))
                else:
                    self.stdout.write(f"No orphaned records found in {collection_name}")
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing {collection_name}: {e}"))
            
            total_orphaned += orphaned_count
            total_cleaned += cleaned_count

        # Summary
        self.stdout.write("\n" + "="*50)
        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN SUMMARY: Found {total_orphaned} orphaned OCR results"))
            self.stdout.write("Run without --dry-run to actually clean them up")
        else:
            self.stdout.write(self.style.SUCCESS(f"CLEANUP SUMMARY: Cleaned up {total_cleaned} orphaned OCR results"))
        
        self.stdout.write(self.style.SUCCESS('Cleanup completed!')) 